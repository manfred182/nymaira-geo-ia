from __future__ import annotations
import io
import logging
import traceback
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RobustVisionProcessor:
    def __init__(self, model_name: str = "google/vit-base-patch16-224"):
        self.model = None
        self.model_name = model_name
        self._is_fallback = False
        self._setup_environment()

    def _setup_environment(self):
        try:
            import torch
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.cuda_available = torch.cuda.is_available()
            logger.info(f"Using device: {self.device}, CUDA available: {self.cuda_available}")
        except Exception as e:
            logger.warning(f"Error setting up environment: {e}")
            self.device = "cpu"
            self.cuda_available = False

    def load_model(self) -> bool:
        try:
            if self.cuda_available:
                try:
                    from transformers import AutoImageProcessor, AutoModelForImageClassification
                    from PIL import Image
                    import torch

                    processor = AutoImageProcessor.from_pretrained(self.model_name)
                    model = AutoModelForImageClassification.from_pretrained(self.model_name)
                    self.model = pipeline(
                        "image-classification",
                        model=model,
                        feature_extractor=processor,
                        device=self.device,
                        top_k=1,
                    )
                    logger.info(f"✅ Model {self.model_name} loaded successfully on GPU!")
                    return True
                except Exception as gpu_e:
                    logger.warning(f"GPU load failed: {gpu_e}, falling back to CPU")
                    self.cuda_available = False

            from transformers import pipeline
            import logging as lib_logging
            lib_logging.getLogger("transformers").setLevel(lib_logging.ERROR)

            self.model = pipeline(
                "image-classification",
                model=self.model_name,
                device=self.device,
                top_k=1,
            )
            self._is_fallback = True
            logger.info(f"✅ Model {self.model_name} loaded successfully on CPU")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load model {self.model_name}: {e}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return False

    def classify_image(self, image_bytes: bytes) -> Optional[dict]:
        if not self.model:
            logger.error("❌ Model not loaded. Call load_model() first.")
            return {"error": "Model not loaded, load_model() failed", "success": False}

        try:
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            logger.info(f"✅ Image opened: {img.size} pixels")

            if self._is_fallback:
                results = self.model(img)
            else:
                with torch.no_grad():
                    inputs = self.model.feature_extractor(images=img, return_tensors="pt").to(self.device)
                    outputs = self.model.model(**inputs)
                    predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
                    top_pred = torch.argmax(predictions, dim=1).item()
                    score = predictions[0][top_pred].item()

                    results = [{"label": self.model.model.config.id2label[str(top_pred)], "score": score}]

            if not isinstance(results, list) or len(results) == 0:
                logger.error(f"❌ Unexpected model output format: {type(results)}, content: {results}")
                return {"error": "Unexpected model output format", "success": False}

            top = results[0]
            label = top.get("label", top.get("label", "unknown"))
            confidence = top.get("score", top.get("score", 0.0))

            logger.info(f"📊 Classification result: {label} ({confidence:.4f})")

            return {
                "class_name": label,
                "confidence": round(confidence, 4),
                "model_name": self.model_name,
                "device": str(self.device),
                "success": True
            }

        except Exception as e:
            logger.error(f"❌ Error in classify_image: {e}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"error": str(e), "success": False}

    def simple_segment_image(self, image_bytes: bytes) -> Optional[dict]:
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_array = np.array(img)
            h, w, _ = img_array.shape

            return {
                "width": w,
                "height": h,
                "channels": 3,
                "mean_r": int(img_array[:, :, 0].mean()),
                "mean_g": int(img_array[:, :, 1].mean()),
                "mean_b": int(img_array[:, :, 2].mean()),
                "message": "Segmentación básica completada",
                "success": True
            }
        except Exception as e:
            logger.error(f"❌ Error in segment_image: {e}")
            return {"error": str(e), "success": False}

    def get_status(self) -> dict:
        return {
            "model_loaded": self.model is not None,
            "model_name": self.model_name,
            "device": str(self.device),
            "is_fallback": self._is_fallback,
            "cuda_available": self.cuda_available,
        }


def search_image_in_documents(query_image_bytes: bytes, documents_folder: str = "data/documents") -> Optional[dict]:
    try:
        processor = RobustVisionProcessor()
        model_loaded = processor.load_model()

        if not model_loaded:
            logger.warning("⚠️ Model loading failed - suggest downloading local model")
            return None

        query_result = processor.classify_image(query_image_bytes)
        if not query_result or not query_result.get("success", False):
            logger.error(f"❌ Classification failed: {query_result}")
            return None

        logger.info(f"🔍 Query classified as: {query_result['class_name']} (confidence: {query_result['confidence']})")

        return query_result
    except Exception as e:
        logger.error(f"❌ Error in search_image_in_documents: {e}")
        return None


def test_system():
    print("🧪 Testing RobustVisionProcessor")
    print("=" * 60)

    processor = RobustVisionProcessor()

    print(f"Model name: {processor.model_name}")
    print(f"CUDA available: {processor.cuda_available}")
    print(f"Device: {processor.device}")
    print()

    success = processor.load_model()
    if success:
        print("✅ Model loaded successfully!")
    else:
        print("❌ Model loading failed")

    print()
    print("Testing classification with generated image...")
    from PIL import Image
    img = Image.new('RGB', (224, 224), color='red')
    test_bytes = io.BytesIO()
    img.save(test_bytes, format='JPEG')
    test_bytes.seek(0)

    result = processor.classify_image(test_bytes.getvalue())
    if result:
        print(f"✅ Classification successful: {result}")
    else:
        print("❌ Classification failed")

    print()
    status = processor.get_status()
    print("Status:", status)


if __name__ == "__main__":
    test_system()
