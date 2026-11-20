import csv
import os
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from PIL import Image, ImageOps

from catalog.models import Category, Product, ProductImage, ProductVariant
from sellers.models import SellerProfile

User = get_user_model()
SEED = Path(settings.BASE_DIR) / "seedings"
RAW = SEED / "raw"
PROCESSED = SEED / "processed"
SIZE = (500, 500)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def process_image(src, dst):
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        fitted = ImageOps.contain(img, SIZE)
        canvas = Image.new("RGB", SIZE, (255, 255, 255))
        canvas.paste(fitted, ((SIZE[0] - fitted.width) // 2, (SIZE[1] - fitted.height) // 2))
        canvas.save(dst, "JPEG", quality=90, optimize=True)


class Command(BaseCommand):
    help = "Seed sellers, categories, products and images from seedings/ (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_all runs only with DEBUG=True.")
        password = os.environ.get("SEED_PASSWORD")
        if not password:
            raise CommandError("Set SEED_PASSWORD first.")

        PROCESSED.mkdir(exist_ok=True)
        brands_by_image = {r["image_file"]: r for r in read_csv(SEED / "brands.csv")}

        plan, skipped = [], []
        for s in read_csv(RAW / "sources.csv"):
            if s["status"] != "FOUND":
                skipped.append(f'{s["brand"]} - {s["product"]} (no official image)')
                continue
            brand = brands_by_image.get(s["image_file"])
            src = RAW / s["image_file"]
            if not brand or not src.exists():
                skipped.append(f'{s["brand"]} - {s["product"]} (image file missing)')
                continue
            plan.append((brand, s["product"], src))

        sellers = {}
        with transaction.atomic():
            for brand, product_name, src in plan:
                profile = self._seller(brand, password)
                sellers[brand["seller_email"]] = brand["brand"]
                subcategory = self._subcategory(brand["category"])
                self._product(brand, product_name, src, profile, subcategory)

        with (SEED / "credentials.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["brand", "login_id", "password"])
            for email, brand_name in sellers.items():
                writer.writerow([brand_name, email, password])

        self.stdout.write(self.style.SUCCESS(
            f"Done: {len(sellers)} sellers, {len(plan)} products. Logins in seedings/credentials.csv"
        ))
        if skipped:
            self.stdout.write(self.style.WARNING("Skipped:"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

    def _seller(self, brand, password):
        email = brand["seller_email"]
        user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
        user.email = email
        user.set_password(password)
        user.save()
        profile, _ = SellerProfile.objects.get_or_create(
            user=user,
            defaults={
                "business_name": brand["brand"],
                "status": SellerProfile.Status.APPROVED,
                "code": slugify(brand["brand"])[:8].upper(),
            },
        )
        return profile

    def _subcategory(self, name):
        parent, _ = Category.objects.get_or_create(
            slug=slugify(name), defaults={"name": name, "parent": None}
        )
        child, _ = Category.objects.get_or_create(
            slug=f"general-{slugify(name)}",
            defaults={"name": "General", "parent": parent},
        )
        return child

    def _product(self, brand, product_name, src, profile, subcategory):
        slug = slugify(f"{brand['brand']} {product_name}")
        product, created = Product.objects.get_or_create(
            slug=slug,
            defaults={
                "seller": profile,
                "subcategory": subcategory,
                "name": product_name,
                "brand": brand["brand"],
                "status": Product.Status.LIVE,
            },
        )
        if not created:
            return
        ProductVariant.objects.create(
            product=product,
            seller=profile,
            label="Standard",
            sku=f"DL-{product.pk}-STD",
            mrp=Decimal(brand["mrp_inr"]),
            price=Decimal(brand["price_inr"]),
            stock=int(brand["stock"]),
            moq=1,
        )
        out = PROCESSED / (Path(src).stem + ".jpg")
        process_image(src, out)
        with out.open("rb") as fh:
            ProductImage.objects.create(
                product=product, alt_text=product_name, sort_order=0,
                image=File(fh, name=out.name),
            )