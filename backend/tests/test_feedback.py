from models.feedback import ChatFeedback


def test_submit_feedback_persists_question_answer_and_rating(client, db_session, project):
    response = client.post(
        f"/api/projects/{project.id}/feedback",
        json={
            "question": "Welche Anforderungen gelten für Brandwände?",
            "answer": "Gemäß DIN 4102-2 müssen Brandwände ...",
            "sources": [
                {
                    "document_id": "doc-1",
                    "filename": "din_4102.pdf",
                    "page_number": 12,
                    "chunk_text": "Brandwände müssen ...",
                    "norm_reference": "DIN 4102-2",
                }
            ],
            "rating": "good",
            "comment": "Sehr hilfreich",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rating"] == "good"
    assert body["comment"] == "Sehr hilfreich"
    assert body["project_id"] == project.id

    stored = db_session.query(ChatFeedback).filter_by(id=body["id"]).one()
    assert stored.question == "Welche Anforderungen gelten für Brandwände?"
    assert stored.answer == "Gemäß DIN 4102-2 müssen Brandwände ..."
    assert stored.rating.value == "good"
    assert "din_4102.pdf" in stored.sources_json


def test_submit_feedback_without_comment(client, project):
    response = client.post(
        f"/api/projects/{project.id}/feedback",
        json={
            "question": "Frage?",
            "answer": "Antwort.",
            "rating": "mid",
        },
    )

    assert response.status_code == 201
    assert response.json()["comment"] is None


def test_submit_feedback_unknown_project_returns_404(client):
    response = client.post(
        "/api/projects/does-not-exist/feedback",
        json={"question": "Frage?", "answer": "Antwort.", "rating": "bad"},
    )

    assert response.status_code == 404


def test_submit_feedback_rejects_invalid_rating(client, project):
    response = client.post(
        f"/api/projects/{project.id}/feedback",
        json={"question": "Frage?", "answer": "Antwort.", "rating": "excellent"},
    )

    assert response.status_code == 422
