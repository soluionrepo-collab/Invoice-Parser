data_extractor="""Return ONLY a valid JSON object. When you reference text elements, include the polygon field with the corresponding index number as a string.
        #     Example format:
        #     {{"field_name": {{"value": "extracted_value", "polygon": "1"}}}}
        #      Data to process: {text_payload}"""


user_payload = """
    items: {compact}
    instruction: Return a JSON object mapping standardized keys to objects that include the original id and text.
    Example: {{Invoice_Number: {{id: 12, "text": "6452526857}}}} Return JSON only.
"""