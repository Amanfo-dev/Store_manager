from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Newest change first, so price_history[0] is the latest one.
    # Deleting an item deletes its price history too.
    price_history = db.relationship(
        "PriceHistory",
        backref="item",
        order_by="PriceHistory.changed_at.desc()",
        cascade="all, delete-orphan",
    )
    # Deleting an item keeps its sales (item_id becomes NULL) so revenue stays correct.
    sales = db.relationship("Sale", backref="item")

    @property
    def latest_price_change(self):
        return self.price_history[0] if self.price_history else None


class PriceHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    old_price = db.Column(db.Float, nullable=False)
    new_price = db.Column(db.Float, nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def difference(self):
        return self.new_price - self.old_price


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=True)
    # Snapshots, so the sale record stays correct if the item is renamed,
    # re-priced or deleted later.
    item_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    sold_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def total(self):
        return self.unit_price * self.quantity


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    spent_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class User(db.Model):
    # Never reuse ids on SQLite, so a removed user's old login cookie can't match a new account.
    __table_args__ = {"sqlite_autoincrement": True}
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")  # admin | manager | employee
    created_at = db.Column(db.DateTime, default=datetime.now)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class RolePermission(db.Model):
    """One row per (role, permission). Admin is never stored: admin can do everything."""
    role = db.Column(db.String(20), primary_key=True)
    perm = db.Column(db.String(40), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    cashier = db.Column(db.String(160), nullable=False, default="")
    sales = db.relationship("Sale", backref="invoice", order_by="Sale.id")

    @property
    def number(self):
        return f"INV-{self.id:05d}"

    @property
    def total(self):
        return sum(s.total for s in self.sales)


class PendingSignup(db.Model):
    """An admin sign-up waiting for its emailed code. The real User row is only
    created once the code is right, so a failed email can never lock sign-up."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
