"""Mask personal details in free text (review comments) before it is stored or sent to a model.

Uses Microsoft Presidio with spaCy's small English model for names and places, plus UK-specific patterns for
phone numbers, postcodes and street addresses that the defaults miss.

    from pipelines.redact import redact
    redact("Call me on 07700 900461")  ->  "Call me on <PHONE>"
"""

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer, PhoneRecognizer, SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# What each kind of detail is replaced with
MASKS = {"PERSON": "<NAME>", "PHONE_NUMBER": "<PHONE>", "EMAIL_ADDRESS": "<EMAIL>",
         "UK_POSTCODE": "<POSTCODE>", "UK_ADDRESS": "<ADDRESS>"}
MIN_SCORE = 0.4
# spaCy's small model sometimes tags dish names ("Halloumi Burger") as people; never mask those
FOOD_WORDS = {"burger", "burgers", "fries", "wings", "tenders", "wrap", "wraps", "shake", "sauce", "mayo", "chicken",
              "beef", "halloumi", "nachos", "rings", "sticks", "momos", "samosa", "patty", "lassi", "cola", "soda",
              "crispy", "spicy", "loaded", "juicy", "cheesy", "smoky", "sticky", "crunchy", "hot", "peri"}

# The default phone check rejects numbers that aren't live (e.g. Ofcom's 07700 900xxx drama range), so match
# the UK formats directly as well
UK_PHONE = PatternRecognizer(supported_entity="PHONE_NUMBER", patterns=[Pattern(
    "uk_phone", r"(?:\+44\s?7\d{3}|\b07\d{3}|\+44\s?[1-3]\d{2,3}|\b0[1-3]\d{2,3})\s?\d{3}\s?\d{3,4}\b", 0.7)])
UK_POSTCODE = PatternRecognizer(supported_entity="UK_POSTCODE", patterns=[Pattern(
    "uk_postcode", r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", 0.6)])
UK_ADDRESS = PatternRecognizer(supported_entity="UK_ADDRESS", patterns=[Pattern(
    "street_address", r"\b(?:(?:flat|apartment|unit)\s+\d+[a-z]?,?\s*)?\d{1,4}[a-z]?\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Close|Drive|Dr|Way|Court|Ct|Place|Terrace|Crescent|Grove)\b", 0.6)])


@lru_cache(maxsize=1)
def engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}).create_engine()
    registry = RecognizerRegistry()
    # Only the recognizers we need: fewer false positives on food words than the full default set
    for recognizer in (SpacyRecognizer(supported_entities=["PERSON"]), EmailRecognizer(),
                       PhoneRecognizer(supported_regions=("GB",)), UK_PHONE, UK_POSTCODE, UK_ADDRESS):
        registry.add_recognizer(recognizer)
    return AnalyzerEngine(nlp_engine=nlp, registry=registry, supported_languages=["en"]), AnonymizerEngine()


def redact(text: str) -> str:
    if not text or not text.strip():
        return text
    analyzer, anonymizer = engines()
    findings = [f for f in analyzer.analyze(text=text, language="en") if f.score >= MIN_SCORE
                and not (f.entity_type == "PERSON" and FOOD_WORDS & set(text[f.start:f.end].lower().split()))]
    if not findings:
        return text
    operators = {entity: OperatorConfig("replace", {"new_value": mask}) for entity, mask in MASKS.items()}
    return anonymizer.anonymize(text=text, analyzer_results=findings, operators=operators).text
