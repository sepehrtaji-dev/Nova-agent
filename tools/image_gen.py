import os
import json
from pathlib import Path

try:
    import torch
except ImportError:
    torch = None

try:
    from diffusers import StableDiffusionPipeline
except ImportError:
    StableDiffusionPipeline = None


class ImageGenTool:
    """Local Stable Diffusion image generation tool for Nova."""

    def __init__(self):
        configured_model = os.getenv("NOVA_IMAGE_MODEL_PATH", "").strip()
        self.model_path = Path(
            configured_model
            if configured_model
            else os.path.join(os.getcwd(), "models", "SD15")
        ).expanduser()
        # Keep generated files inside the active Nova workspace on every machine.
        self.output_dir = Path(os.path.abspath(
            os.path.join(os.getcwd(), "projects", "generated_images")
        ))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pipe = None
        self.device = (
            "cuda"
            if torch is not None and torch.cuda.is_available()
            else "cpu"
        )

    def _load_pipeline(self):
        """Lazy load the Stable Diffusion pipeline."""
        if self.pipe is None:
            if torch is None:
                return False, "PyTorch is not installed."
            if StableDiffusionPipeline is None:
                return False, "diffusers is not installed."
            if not self.model_path.exists():
                return False, f"Model not found at {self.model_path}"

            try:
                self.pipe = StableDiffusionPipeline.from_pretrained(
                    self.model_path,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                    safety_checker=None,
                    requires_safety_checker=False,
                ).to(self.device)

                # Enable memory efficient attention if on CUDA
                if self.device == "cuda":
                    self.pipe.enable_attention_slicing()
                    try:
                        self.pipe.enable_xformers_memory_efficient_attention()
                    except Exception:
                        # xformers not available, skip
                        pass

            except Exception as e:
                return False, f"Failed to load model: {type(e).__name__}: {e}"

        return True, None

    def _parse_input(self, input_data):
        """Parse JSON or plain string input."""
        if isinstance(input_data, dict):
            return input_data

        if not isinstance(input_data, str):
            return {}

        try:
            data = json.loads(input_data.strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        return {"prompt": input_data.strip()}

    def run(self, input_data):
        """
        Generate an image from a prompt.

        Input JSON:
        {
            "prompt": "a beautiful sunset over mountains",  # required
            "negative_prompt": "blurry, low quality",       # optional
            "width": 512,                                    # optional, default 512
            "height": 512,                                   # optional, default 512
            "num_inference_steps": 20,                       # optional, default 20
            "guidance_scale": 7.5,                           # optional, default 7.5
            "seed": 42,                                      # optional, default random
            "filename": "generated_image.png"                # optional, default auto
        }
        """
        data = self._parse_input(input_data)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return "IMAGE ERROR: 'prompt' is required."

        # Parse parameters with defaults
        negative_prompt = data.get("negative_prompt", "").strip() or None
        width = int(data.get("width", 512))
        height = int(data.get("height", 512))
        steps = int(data.get("num_inference_steps", 20))
        guidance = float(data.get("guidance_scale", 7.5))
        seed = data.get("seed")
        filename = data.get("filename", "").strip()

        if width <= 0 or height <= 0 or width > 2048 or height > 2048:
            return "IMAGE ERROR: width and height must be between 1 and 2048."
        if width % 8 or height % 8:
            return "IMAGE ERROR: width and height must be multiples of 8."
        if steps < 1 or steps > 100:
            return "IMAGE ERROR: num_inference_steps must be between 1 and 100."
        if guidance < 0 or guidance > 30:
            return "IMAGE ERROR: guidance_scale must be between 0 and 30."

        # A filename is metadata, never a path. Prevent traversal outside output_dir.
        if filename:
            filename = Path(filename).name
            if not filename:
                return "IMAGE ERROR: invalid filename."

        # Load pipeline
        ok, error = self._load_pipeline()
        if not ok:
            return f"IMAGE ERROR: {error}"

        # Set seed if provided
        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(int(seed))

        try:
            # Generate image
            result = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=generator,
            )

            image = result.images[0]

            # Save image
            if not filename:
                import uuid
                filename = f"generated_{uuid.uuid4().hex[:8]}.png"
            elif not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                filename += ".png"

            output_path = self.output_dir / filename
            image.save(output_path)

            return (
                f"IMAGE GENERATED\n"
                f"Prompt: {prompt}\n"
                f"Negative prompt: {negative_prompt or 'none'}\n"
                f"Size: {width}x{height}\n"
                f"Steps: {steps}\n"
                f"Guidance: {guidance}\n"
                f"Seed: {seed or 'random'}\n"
                f"Saved to: {output_path}\n"
                f"STATUS: SUCCESS"
            )

        except torch.cuda.OutOfMemoryError:
            return "IMAGE ERROR: CUDA out of memory. Try smaller resolution or fewer steps."
        except Exception as e:
            return f"IMAGE ERROR: {type(e).__name__}: {e}"


if __name__ == "__main__":
    # Quick test
    tool = ImageGenTool()
    print("Testing image generation...")
    result = tool.run('{"prompt": "a simple test image, red circle on white background", "width": 256, "height": 256, "num_inference_steps": 5}')
    print(result)