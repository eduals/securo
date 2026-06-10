# backend/tests/test_new_rules_api.py
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.category_service import create_default_categories
from app.services.rule_service import create_default_rules



@pytest.mark.asyncio
async def test_list_rules_empty(client: AsyncClient, auth_headers, test_categories):
    """Listing rules with no data should return an empty list."""
    response = await client.get("/api/rules", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_rules_with_defaults(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user: User
):
    """After creating default categories and rules (as registration does), listing returns them."""
    await create_default_categories(session, test_user.id, "pt-BR")
    await create_default_rules(session, test_user.id, "pt-BR")

    response = await client.get("/api/rules", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    # Each rule has the expected structure
    rule = data[0]
    assert "conditions" in rule
    assert "actions" in rule
    assert "conditions_op" in rule


@pytest.mark.asyncio
async def test_create_rule(client: AsyncClient, auth_headers, test_categories):
    cat_id = str(test_categories[0].id)
    payload = {
        "name": "Test Rule",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "IFOOD"}],
        "actions": [{"op": "set_category", "value": cat_id}],
        "priority": 5,
        "is_active": True,
    }
    response = await client.post("/api/rules", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Rule"
    assert data["conditions"][0]["value"] == "IFOOD"


@pytest.mark.asyncio
async def test_update_rule(client: AsyncClient, auth_headers, test_rules):
    rule_id = str(test_rules[0].id)
    response = await client.patch(
        f"/api/rules/{rule_id}",
        json={"name": "Updated Name"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_rule(client: AsyncClient, auth_headers, test_rules):
    rule_id = str(test_rules[0].id)
    response = await client.delete(f"/api/rules/{rule_id}", headers=auth_headers)
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_apply_all_rules(client: AsyncClient, auth_headers, test_rules, test_transactions):
    response = await client.post("/api/rules/apply-all", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "applied" in data
    assert data["applied"] >= 3  # 3 of 5 transactions match rules


# --- Integration tests: category assignment, tags, priority, isolation ---


@pytest.mark.asyncio
async def test_apply_all_verifies_category_assignment(
    client: AsyncClient, auth_headers, test_rules, test_transactions, test_categories,
):
    """After apply-all, GET transactions and confirm correct category_id."""
    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["items"]

    # Build a lookup by description
    by_desc = {t["description"]: t for t in items}

    # UBER TRIP should be categorised as Transporte (test_categories[1])
    uber = by_desc.get("UBER TRIP")
    assert uber is not None
    assert uber["category_id"] == str(test_categories[1].id)

    # IFOOD RESTAURANTE -> Alimentação (test_categories[0])
    ifood = by_desc.get("IFOOD RESTAURANTE")
    assert ifood is not None
    assert ifood["category_id"] == str(test_categories[0].id)

    # SALARIO FEV -> Receita (test_categories[2])
    salario = by_desc.get("SALARIO FEV")
    assert salario is not None
    assert salario["category_id"] == str(test_categories[2].id)


@pytest.mark.asyncio
async def test_apply_all_resets_before_reapply(
    client: AsyncClient, auth_headers, test_rules, test_transactions, test_categories,
):
    """Category/notes are reset before re-applying, so results are idempotent."""
    # Apply once
    await client.post("/api/rules/apply-all", headers=auth_headers)

    # Apply again — should produce same results
    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    by_desc = {t["description"]: t for t in items}

    uber = by_desc.get("UBER TRIP")
    assert uber["category_id"] == str(test_categories[1].id)


@pytest.mark.asyncio
async def test_conflicting_rules_priority(
    client: AsyncClient, auth_headers, test_transactions, test_categories,
):
    """Two rules match same transaction; lower priority number wins category."""
    cat_food = str(test_categories[0].id)  # Alimentação
    cat_transport = str(test_categories[1].id)  # Transporte

    # Create a low-priority rule (runs first) matching UBER -> Alimentação
    low_rule = {
        "name": "Low priority UBER",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "UBER"}],
        "actions": [{"op": "set_category", "value": cat_food}],
        "priority": 1,
        "is_active": True,
    }
    # Create a high-priority rule (runs later) matching UBER -> Transporte
    high_rule = {
        "name": "High priority UBER",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "UBER"}],
        "actions": [{"op": "set_category", "value": cat_transport}],
        "priority": 99,
        "is_active": True,
    }
    resp1 = await client.post("/api/rules", json=low_rule, headers=auth_headers)
    resp2 = await client.post("/api/rules", json=high_rule, headers=auth_headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 201

    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    by_desc = {t["description"]: t for t in items}

    uber = by_desc.get("UBER TRIP")
    assert uber is not None
    # Lower priority (1) wins, so category should be Alimentação
    assert uber["category_id"] == cat_food


@pytest.mark.asyncio
async def test_tag_attribution_via_rules(
    client: AsyncClient, auth_headers, test_transactions, test_categories,
):
    """Rule with append_notes applies tags, verify on transaction."""
    cat_transport = str(test_categories[1].id)
    rule_payload = {
        "name": "Tag UBER trips",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "UBER"}],
        "actions": [
            {"op": "set_category", "value": cat_transport},
            {"op": "append_notes", "value": "#transport #rideshare"},
        ],
        "priority": 1,
        "is_active": True,
    }
    resp = await client.post("/api/rules", json=rule_payload, headers=auth_headers)
    assert resp.status_code == 201

    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    by_desc = {t["description"]: t for t in items}

    uber = by_desc.get("UBER TRIP")
    assert uber is not None
    assert "#transport" in (uber.get("notes") or "")
    assert "#rideshare" in (uber.get("notes") or "")


@pytest.mark.asyncio
async def test_multiple_tags_from_multiple_rules(
    client: AsyncClient, auth_headers, test_transactions, test_categories,
):
    """Two rules append different tags to the same transaction."""
    rule1 = {
        "name": "Tag debit",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "UBER"}],
        "actions": [{"op": "append_notes", "value": "#expense"}],
        "priority": 1,
        "is_active": True,
    }
    rule2 = {
        "name": "Tag rideshare",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "UBER"}],
        "actions": [{"op": "append_notes", "value": "#rideshare"}],
        "priority": 2,
        "is_active": True,
    }
    resp1 = await client.post("/api/rules", json=rule1, headers=auth_headers)
    resp2 = await client.post("/api/rules", json=rule2, headers=auth_headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 201

    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    by_desc = {t["description"]: t for t in items}

    uber = by_desc.get("UBER TRIP")
    assert uber is not None
    notes = uber.get("notes") or ""
    assert "#expense" in notes
    assert "#rideshare" in notes


@pytest.mark.asyncio
async def test_inactive_rule_is_skipped(
    client: AsyncClient, auth_headers, test_transactions, test_categories,
):
    """Disabled rule should not apply."""
    cat_food = str(test_categories[0].id)
    rule_payload = {
        "name": "Inactive NETFLIX rule",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "NETFLIX"}],
        "actions": [{"op": "set_category", "value": cat_food}],
        "priority": 1,
        "is_active": False,
    }
    resp = await client.post("/api/rules", json=rule_payload, headers=auth_headers)
    assert resp.status_code == 201

    await client.post("/api/rules/apply-all", headers=auth_headers)

    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    by_desc = {t["description"]: t for t in items}

    netflix = by_desc.get("NETFLIX")
    assert netflix is not None
    # No active rule matches NETFLIX, so category should be None
    assert netflix["category_id"] is None


@pytest.mark.asyncio
async def test_rule_user_isolation(
    client: AsyncClient, auth_headers, test_rules, test_transactions, session: AsyncSession,
):
    """One user's rules don't affect another user's transactions."""
    import bcrypt as _bcrypt
    from app.services.workspace_service import create_personal_workspace_for_user

    # Create second user
    hashed = _bcrypt.hashpw(b"otherpass123", _bcrypt.gensalt()).decode()
    user2 = User(
        id=uuid.uuid4(),
        email="other@example.com",
        hashed_password=hashed,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        preferences={"language": "pt-BR", "date_format": "DD/MM/YYYY",
                      "timezone": "America/Sao_Paulo", "currency_display": "BRL"},
    )
    session.add(user2)
    await session.flush()
    await create_personal_workspace_for_user(session, user2)
    await session.commit()

    # Login as user2
    login_resp = await client.post(
        "/api/auth/login",
        data={"username": "other@example.com", "password": "otherpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    user2_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # User2 apply-all should not process user1's transactions
    response = await client.post("/api/rules/apply-all", headers=user2_headers)
    assert response.status_code == 200
    assert response.json()["applied"] == 0

    # User1's transactions should remain unchanged by user2's apply-all
    response = await client.get("/api/transactions", headers=auth_headers)
    items = response.json()["items"]
    # Verify user1 still has transactions
    assert len(items) >= 5


@pytest.mark.asyncio
async def test_add_description_to_rule_appends_and_sets_or(
    client: AsyncClient, auth_headers, test_categories
):
    """Adding a description appends a condition and flips conditions_op to 'or'
    when every condition targets the description field."""
    cat_id = str(test_categories[0].id)
    rule = (await client.post("/api/rules", json={
        "name": "Streaming",
        "conditions_op": "and",
        "conditions": [{"field": "description", "op": "contains", "value": "Netflix"}],
        "actions": [{"op": "set_category", "value": cat_id}],
    }, headers=auth_headers)).json()

    resp = await client.post(
        f"/api/rules/{rule['id']}/add-description",
        json={"description": "Spotify"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    descs = [c["value"] for c in updated["conditions"] if c["field"] == "description"]
    assert "Netflix" in descs and "Spotify" in descs
    assert updated["conditions_op"] == "or"


@pytest.mark.asyncio
async def test_add_description_to_rule_is_idempotent(
    client: AsyncClient, auth_headers, test_categories
):
    cat_id = str(test_categories[0].id)
    rule = (await client.post("/api/rules", json={
        "name": "Food",
        "conditions_op": "or",
        "conditions": [{"field": "description", "op": "contains", "value": "iFood"}],
        "actions": [{"op": "set_category", "value": cat_id}],
    }, headers=auth_headers)).json()

    # Same description (different case) should not duplicate.
    resp = await client.post(
        f"/api/rules/{rule['id']}/add-description",
        json={"description": "IFOOD"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    descs = [c["value"] for c in resp.json()["conditions"] if c["field"] == "description"]
    assert len(descs) == 1


@pytest.mark.asyncio
async def test_add_description_to_unknown_rule_404(client: AsyncClient, auth_headers):
    resp = await client.post(
        f"/api/rules/{uuid.uuid4()}/add-description",
        json={"description": "X"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_matching_rules_returns_active_category_rule(
    client: AsyncClient, auth_headers, test_account, test_categories
):
    cat_id = str(test_categories[0].id)
    await client.post("/api/rules", json={
        "name": "Streaming",
        "conditions_op": "or",
        "conditions": [{"field": "description", "op": "contains", "value": "Netflix"}],
        "actions": [{"op": "set_category", "value": cat_id}],
    }, headers=auth_headers)
    tx = (await client.post("/api/transactions", json={
        "account_id": str(test_account.id), "description": "NETFLIX.COM",
        "amount": "39.90", "date": "2026-06-01", "type": "debit",
    }, headers=auth_headers)).json()

    resp = await client.get(f"/api/transactions/{tx['id']}/matching-rules", headers=auth_headers)
    assert resp.status_code == 200
    rules = resp.json()["rules"]
    assert any(r["name"] == "Streaming" for r in rules)


@pytest.mark.asyncio
async def test_matching_rules_empty_when_no_category_rule(
    client: AsyncClient, auth_headers, test_account, test_categories
):
    tx = (await client.post("/api/transactions", json={
        "account_id": str(test_account.id), "description": "Algo Unico XYZ",
        "amount": "10.00", "date": "2026-06-01", "type": "debit",
    }, headers=auth_headers)).json()
    resp = await client.get(f"/api/transactions/{tx['id']}/matching-rules", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["rules"] == []


@pytest.mark.asyncio
async def test_matching_rules_ignores_non_category_rules(
    client: AsyncClient, auth_headers, test_account, test_categories
):
    await client.post("/api/rules", json={
        "name": "NotesOnly",
        "conditions_op": "or",
        "conditions": [{"field": "description", "op": "contains", "value": "Spotify"}],
        "actions": [{"op": "append_notes", "value": "#music"}],
    }, headers=auth_headers)
    tx = (await client.post("/api/transactions", json={
        "account_id": str(test_account.id), "description": "SPOTIFY P1",
        "amount": "19.90", "date": "2026-06-01", "type": "debit",
    }, headers=auth_headers)).json()
    resp = await client.get(f"/api/transactions/{tx['id']}/matching-rules", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["rules"] == []


@pytest.mark.asyncio
async def test_matching_rules_unknown_tx_404(client: AsyncClient, auth_headers):
    import uuid as _uuid
    resp = await client.get(f"/api/transactions/{_uuid.uuid4()}/matching-rules", headers=auth_headers)
    assert resp.status_code == 404
