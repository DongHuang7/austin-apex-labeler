from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from contact_scan import scan_all_accounts
from contacts.gmail_contacts import apply_labels_bulk, create_contact, label_contact
from models import ContactReview, db

bp = Blueprint("contacts", __name__, url_prefix="/contacts")

VALID_CATEGORIES = {"Buyer", "Seller", "Broker", "Other"}


@bp.route("/review")
@login_required
def review():
    account = request.args.get("account")
    category = request.args.get("category")

    query = ContactReview.query.filter_by(status="pending")
    if account:
        query = query.filter_by(account=account)
    if category:
        query = query.filter_by(suggested_category=category)

    rows = query.order_by(ContactReview.detected_at.desc()).all()
    return render_template(
        "contacts_review.html",
        rows=rows,
        categories=sorted(VALID_CATEGORIES),
        selected_account=account,
        selected_category=category,
    )


@bp.route("/review/scan", methods=["POST"])
@login_required
def scan():
    results = scan_all_accounts()
    ok = {a: r["count"] for a, r in results.items() if r["error"] is None}
    failed = {a: r["error"] for a, r in results.items() if r["error"] is not None}

    if ok:
        total = sum(ok.values())
        flash(f"Scan complete — {total} new contact(s) found "
              f"({', '.join(f'{a}: {c}' for a, c in ok.items())}).")
    for account, error in failed.items():
        flash(f"Couldn't scan {account}: {error}", "error")

    return redirect(url_for("contacts.review"))


@bp.route("/review/<int:row_id>/approve", methods=["POST"])
@login_required
def approve(row_id):
    row = db.get_or_404(ContactReview, row_id)
    category = request.form.get("category", row.suggested_category)
    if category not in VALID_CATEGORIES:
        flash(f"Invalid category '{category}'.", "error")
        return redirect(url_for("contacts.review"))

    row.final_category = category
    row.status = "approved"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = current_user.id
    db.session.commit()

    try:
        resource_name = label_contact(
            email=row.email,
            name=row.name,
            label=category,
            account=row.account,
            resource_name=row.resource_name,
        )
        row.resource_name = resource_name
        row.status = "applied"
        row.applied_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as e:
        row.status = "failed"
        row.error = str(e)
        db.session.commit()
        flash(f"Failed to apply label for {row.email}: {e}", "error")

    return redirect(url_for("contacts.review"))


@bp.route("/review/<int:row_id>/reject", methods=["POST"])
@login_required
def reject(row_id):
    row = db.get_or_404(ContactReview, row_id)
    row.status = "rejected"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = current_user.id
    db.session.commit()
    return redirect(url_for("contacts.review"))


@bp.route("/review/bulk_approve", methods=["POST"])
@login_required
def bulk_approve():
    row_ids = [int(x) for x in request.form.getlist("row_id")]
    rows = ContactReview.query.filter(ContactReview.id.in_(row_ids)).all()

    # Group by (account, category) since apply_labels_bulk operates on one
    # account/label set at a time.
    groups = {}
    now = datetime.now(timezone.utc)
    for row in rows:
        category = request.form.get(f"category_{row.id}", row.suggested_category)
        if category not in VALID_CATEGORIES:
            continue
        row.final_category = category
        row.status = "approved"
        row.decided_at = now
        row.decided_by = current_user.id
        groups.setdefault(row.account, {}).setdefault(category, []).append(row)
    db.session.commit()

    for account, by_category in groups.items():
        # apply_labels_bulk only relabels contacts that already have a
        # resource_name — brand-new senders from the Gmail scan don't, so
        # create those Google Contacts first.
        for category, group_rows in by_category.items():
            for row in group_rows:
                if not row.resource_name:
                    try:
                        row.resource_name = create_contact(row.email, row.name, account=account)
                    except Exception as e:
                        row.status = "failed"
                        row.error = f"Could not create contact: {e}"

        contacts_by_label = {cat: [] for cat in VALID_CATEGORIES}
        for category, group_rows in by_category.items():
            for row in group_rows:
                if row.resource_name:
                    contacts_by_label[category].append({
                        "resource_name": row.resource_name,
                        "email": row.email,
                        "name": row.name,
                    })

        try:
            apply_labels_bulk(contacts_by_label, account=account)
            for category, group_rows in by_category.items():
                for row in group_rows:
                    if row.status != "failed":
                        row.status = "applied"
                        row.applied_at = now
        except Exception as e:
            for category, group_rows in by_category.items():
                for row in group_rows:
                    row.status = "failed"
                    row.error = str(e)
            flash(f"Bulk apply failed for account {account}: {e}", "error")
    db.session.commit()

    return redirect(url_for("contacts.review"))


@bp.route("/review/history")
@login_required
def history():
    rows = (
        ContactReview.query.filter(ContactReview.status.in_(["applied", "rejected", "failed"]))
        .order_by(ContactReview.decided_at.desc())
        .limit(200)
        .all()
    )
    return render_template("contacts_history.html", rows=rows)
