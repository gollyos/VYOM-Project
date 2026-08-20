from __future__ import annotations

from fastapi import APIRouter, Request

from app.contacts.schemas import Contact, ContactResolution


router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("/resolve", response_model=ContactResolution)
async def resolve_contact(query: str, request: Request) -> ContactResolution:
    records = await request.app.state.crm_store.list()
    contacts = [Contact(id=item.id, display_name=item.name, emails=[email] if (email := getattr(item, "contact_email", None)) else [], company=getattr(item, "company", None)) for item in records]
    request.app.state.contact_resolver.replace(contacts)
    return request.app.state.contact_resolver.resolve(query)
