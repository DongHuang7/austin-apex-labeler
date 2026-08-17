import base64
import time
from googleapiclient.discovery import build
from auth.google_auth import get_credentials


def _extract_contact(person):
    name = ""
    email = ""
    job_title = ""
    company = ""
    notes = ""

    names = person.get("names", [])
    if names:
        name = names[0].get("displayName", "")

    emails = person.get("emailAddresses", [])
    if emails:
        email = emails[0].get("value", "")

    orgs = person.get("organizations", [])
    if orgs:
        job_title = orgs[0].get("title", "")
        company = orgs[0].get("name", "")

    bios = person.get("biographies", [])
    if bios:
        notes = bios[0].get("value", "")

    return name, email, job_title, company, notes


def fetch_all_contacts(account: str = "default"):
    creds = get_credentials(account)
    service = build("people", "v1", credentials=creds)

    contacts = []
    seen_emails = set()

    # Fetch saved contacts
    page_token = None
    while True:
        results = service.people().connections().list(
            resourceName="people/me",
            pageSize=1000,
            personFields="names,emailAddresses,organizations,biographies",
            pageToken=page_token,
        ).execute()

        for person in results.get("connections", []):
            name, email, job_title, company, notes = _extract_contact(person)
            if email and email not in seen_emails:
                seen_emails.add(email)
                contacts.append({
                    "resource_name": person.get("resourceName", ""),
                    "name": name,
                    "email": email,
                    "job_title": job_title,
                    "company": company,
                    "notes": notes,
                })

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    # Fetch "Other contacts" (auto-saved from Gmail history)
    page_token = None
    while True:
        results = service.otherContacts().list(
            pageSize=1000,
            readMask="names,emailAddresses",
            pageToken=page_token,
        ).execute()

        for person in results.get("otherContacts", []):
            name, email, job_title, company, notes = _extract_contact(person)
            if email and email not in seen_emails:
                seen_emails.add(email)
                contacts.append({
                    "resource_name": person.get("resourceName", ""),
                    "name": name,
                    "email": email,
                    "job_title": job_title,
                    "company": company,
                    "notes": notes,
                })

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    print(f"Fetched {len(contacts)} contacts.")
    return contacts


def check_keyword_in_emails(contact_email: str, keyword: str, account: str = "default") -> bool:
    """Search Gmail for emails with this contact containing a specific keyword."""
    creds = get_credentials(account)
    service = build("gmail", "v1", credentials=creds)

    query = f"(from:{contact_email} OR to:{contact_email}) {keyword}"
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=1,
    ).execute()

    return len(results.get("messages", [])) > 0


def fetch_email_snippets(contact_email: str, max_messages: int = 10, account: str = "default") -> str:
    """Fetch recent email snippets exchanged with a contact."""
    creds = get_credentials(account)
    service = build("gmail", "v1", credentials=creds)

    query = f"from:{contact_email} OR to:{contact_email}"
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_messages,
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return ""

    snippets = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["Subject"],
        ).execute()
        subject = ""
        for header in detail.get("payload", {}).get("headers", []):
            if header["name"] == "Subject":
                subject = header["value"]
                break
        snippet = detail.get("snippet", "")
        if subject or snippet:
            snippets.append(f"Subject: {subject}\nSnippet: {snippet}")

    return "\n\n".join(snippets)


def save_other_contact(service, resource_name: str) -> str:
    """Copy an otherContact to regular contacts and return the new resource name."""
    result = service.otherContacts().copyOtherContactToMyContactsGroup(
        resourceName=resource_name,
        body={"copyMask": "names,emailAddresses"},
    ).execute()
    return result.get("resourceName", "")


def _modify_group(service, group_resource, add=None, remove=None):
    """Add or remove resource names from a contact group with retry."""
    body = {}
    if add:
        body["resourceNamesToAdd"] = add
    if remove:
        body["resourceNamesToRemove"] = remove
    if not body:
        return
    for attempt in range(3):
        try:
            service.contactGroups().members().modify(
                resourceName=group_resource,
                body=body,
            ).execute()
            return
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"  ✗ Group modify failed: {e}")


def apply_labels_bulk(contacts_by_label: dict, account: str = "default"):
    """
    Apply labels to contacts, removing any old category labels first.
    contacts_by_label: {"Buyer": [contact, ...], "Broker": [...], ...}
    """
    creds = get_credentials(account)
    service = build("people", "v1", credentials=creds)

    category_labels = ["Buyer", "Seller", "Broker", "Other"]

    group_resources = {
        label: get_or_create_contact_group(service, label)
        for label in category_labels
    }

    correct_label = {}
    for label, contacts in contacts_by_label.items():
        for c in contacts:
            rn = c["resource_name"]
            if rn.startswith("otherContacts/"):
                rn = save_other_contact(service, rn)
                if not rn:
                    print(f"  ✗ Could not save {c['email']} to contacts")
                    continue
                time.sleep(0.3)
                c["resource_name"] = rn
            correct_label[rn] = label

    for label in category_labels:
        group_resource = group_resources[label]

        try:
            detail = service.contactGroups().get(
                resourceName=group_resource,
                maxMembers=2000,
            ).execute()
            current_members = set(detail.get("memberResourceNames", []))
        except Exception:
            current_members = set()

        should_be_members = {rn for rn, lbl in correct_label.items() if lbl == label}
        to_add = list(should_be_members - current_members)
        to_remove = list(current_members & {rn for rn, lbl in correct_label.items() if lbl != label})

        if to_add:
            print(f"  Adding {len(to_add)} contacts to '{label}'...")
            for i in range(0, len(to_add), 50):
                _modify_group(service, group_resource, add=to_add[i:i+50])

        if to_remove:
            print(f"  Removing {len(to_remove)} mis-labeled contacts from '{label}'...")
            for i in range(0, len(to_remove), 50):
                _modify_group(service, group_resource, remove=to_remove[i:i+50])


def apply_label_to_contact(resource_name: str, label: str, account: str = "default"):
    creds = get_credentials(account)
    service = build("people", "v1", credentials=creds)

    if resource_name.startswith("otherContacts/"):
        resource_name = save_other_contact(service, resource_name)
        if not resource_name:
            return

    group_resource = get_or_create_contact_group(service, label)

    for attempt in range(3):
        try:
            service.contactGroups().members().modify(
                resourceName=group_resource,
                body={"resourceNamesToAdd": [resource_name]},
            ).execute()
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def create_contact(email: str, name: str, account: str = "default") -> str:
    """Create a brand-new Google Contact (for senders that aren't in
    Contacts or otherContacts at all yet) and return its resourceName.
    Retries on 429/Quota errors, matching the old run_apply_pending.py."""
    creds = get_credentials(account)
    service = build("people", "v1", credentials=creds)

    given, _, family = (name or "").partition(" ")
    body = {"emailAddresses": [{"value": email}]}
    if given or family:
        body["names"] = [{"givenName": given, "familyName": family}]

    for attempt in range(4):
        try:
            result = service.people().createContact(body=body).execute()
            return result.get("resourceName", "")
        except Exception as e:
            if attempt < 3 and ("429" in str(e) or "Quota" in str(e)):
                time.sleep(15 * (attempt + 1))
            else:
                raise


def label_contact(email: str, name: str, label: str, account: str = "default", resource_name: str = None) -> str:
    """Review-inbox entry point for a single contact: creates the Google
    Contact if it doesn't exist yet (new senders from the Gmail scan have no
    resource_name), promotes otherContacts if needed, then adds it to the
    label group. Returns the resource_name actually used."""
    if not resource_name:
        resource_name = create_contact(email, name, account=account)
    apply_label_to_contact(resource_name, label, account=account)
    return resource_name


def get_or_create_contact_group(service, label: str) -> str:
    """Returns the resourceName of the contact group, creating it if needed."""
    groups = service.contactGroups().list().execute()
    for group in groups.get("contactGroups", []):
        if group.get("name", "").lower() == label.lower():
            return group["resourceName"]

    new_group = service.contactGroups().create(
        body={"contactGroup": {"name": label}}
    ).execute()
    return new_group["resourceName"]


def fetch_contacts_by_group(label: str, account: str = "default"):
    """Fetch all contacts that belong to a specific label/group."""
    creds = get_credentials(account)
    service = build("people", "v1", credentials=creds)

    groups = service.contactGroups().list().execute()
    group_resource = None
    for group in groups.get("contactGroups", []):
        if group.get("name", "").lower() == label.lower():
            group_resource = group["resourceName"]
            break

    if not group_resource:
        print(f"No group found with label: {label}")
        return []

    group_detail = service.contactGroups().get(
        resourceName=group_resource,
        maxMembers=1000,
    ).execute()

    member_resource_names = group_detail.get("memberResourceNames", [])
    if not member_resource_names:
        return []

    response = service.people().getBatchGet(
        resourceNames=member_resource_names,
        personFields="names,emailAddresses,organizations",
    ).execute()

    contacts = []
    for person_response in response.get("responses", []):
        person = person_response.get("person", {})
        name = ""
        email = ""

        names = person.get("names", [])
        if names:
            name = names[0].get("displayName", "")

        emails = person.get("emailAddresses", [])
        if emails:
            email = emails[0].get("value", "")

        if email:
            contacts.append({"name": name, "email": email})

    return contacts
