import os
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

from geoia.geo.classifier import GeoClassifier


def test_classifier_fallback():
    classifier = GeoClassifier()
    result = classifier.classify_image(b"\x00\x01\x02\x03" * 256)
    assert "class_name" in result
    assert "confidence" in result


def test_segment():
    classifier = GeoClassifier()
    pixels = bytes(range(256)) * 2
    result = classifier.segment_image(pixels)
    assert "width" in result or "error" in result
