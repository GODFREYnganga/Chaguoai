def to_fhir_patient(user_data):
    """Maps Firestore user data to a basic FHIR R4 Patient resource."""
    return {
        "resourceType": "Patient",
        "id": user_data.get("phone", "unknown").replace("+", ""),
        "identifier": [{"system": "tel", "value": user_data.get("phone")}],
        "name": [{"text": user_data.get("name", "Anonymous Client")}],
        "extension": [
            {
                "url": "http://chaguoai.ke/fhir/assigned_provider",
                "valueString": user_data.get("assigned_provider_id"),
            }
        ],
    }
