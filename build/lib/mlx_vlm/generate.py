import argparse
import codecs
from pathlib import Path

import mlx.core as mx
import numpy as np
import requests
from .utils import get_model_class
from PIL import Image
from transformers import AutoProcessor, AutoConfig

MODEL_TYPE = ""
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate text from an image using a model."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qnguyen3/nanoLLaVA",
        help="The path to the local model directory or Hugging Face repo.",
    )
    parser.add_argument(
        "--image",
        type=str,
        default="http://images.cocodataset.org/val2017/000000039769.jpg",
        help="URL or path of the image to process.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="<image>\nWhat are these?",
        help="Message to be processed by the model.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100,
        help="Maximum number of tokens to generate.",
    )
    parser.add_argument(
        "--temp", type=float, default=0.3, help="Temperature for sampling."
    )
    return parser.parse_args()


def load_image(image_source):
    """
    Helper function to load an image from either a URL or file.
    """
    if image_source.startswith(("http://", "https://")):
        try:
            response = requests.get(image_source, stream=True)
            response.raise_for_status()
            return Image.open(response.raw)
        except Exception as e:
            raise ValueError(
                f"Failed to load image from URL: {image_source} with error {e}"
            )
    elif Path(image_source).is_file():
        try:
            return Image.open(image_source)
        except IOError as e:
            raise ValueError(f"Failed to load image {image_source} with error: {e}")
    else:
        raise ValueError(
            f"The image {image_source} must be a valid URL or existing file."
        )


def prepare_inputs(image_processor, processor, image, prompt):
    if isinstance(image, str):
        image = load_image(image)

    if MODEL_TYPE == "nanoLlava":
        text_chunks = [processor(chunk).input_ids for chunk in prompt.split("<image>")]
        input_ids = mx.array([text_chunks[0] + [-200] + text_chunks[1]])
        pixel_values = image_processor.preprocess([image])[0]
        pixel_values = mx.array(np.expand_dims(pixel_values, axis=0))
    else:
        inputs = processor(prompt, image, return_tensors="np")
        pixel_values = mx.array(inputs["pixel_values"])
        input_ids = mx.array(inputs["input_ids"])

    return input_ids, pixel_values


def load_model(model_path):
    global MODEL_TYPE
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    model_class, MODEL_TYPE, image_processor = get_model_class(config.to_dict())
    model = model_class.Model.from_pretrained(model_path)
    return processor, model, image_processor


def sample(logits, temperature=0.0):
    if temperature == 0:
        return mx.argmax(logits, axis=-1)
    else:
        return mx.random.categorical(logits * (1 / temperature))


def generate_text(input_ids, pixel_values, model, processor, max_tokens, temperature):

    logits, cache = model(input_ids, pixel_values)
    logits = logits[:, -1, :]
    y = sample(logits, temperature=temperature)
    tokens = [y.item()]

    for n in range(max_tokens - 1):
        logits, cache = model.language_model(y[None], cache=cache)
        logits = logits[:, -1, :]
        y = sample(logits, temperature)
        token = y.item()
        if token == processor.eos_token_id:
            break
        tokens.append(token)

    return processor.decode(tokens)


def main():
    args = parse_arguments()
    processor, model, image_processor = load_model(args.model)

    prompt = codecs.decode(args.prompt, "unicode_escape")

    if "chat_template" in processor.__dict__.keys():
        prompt = processor.apply_chat_template(
            [{"role": "user", "content": f"{prompt}"}],
            tokenize=False,
            add_generation_prompt=True,
        )
    elif "tokenizer" in processor.__dict__.keys():
        prompt = processor.tokenizer.apply_chat_template(
            [{"role": "user", "content": f"{prompt}"}],
            tokenize=False,
            add_generation_prompt=True,
        )
    else:
        ValueError("Error: processor does not have 'chat_template' or 'tokenizer' attribute.")

    input_ids, pixel_values = prepare_inputs(image_processor, processor, args.image, prompt)

    generated_text = generate_text(
        input_ids, pixel_values, model, processor, args.max_tokens, args.temp
    )
    print(generated_text)


if __name__ == "__main__":
    main()