import asyncio
import logging
import html
import aiohttp
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Holatlar sinfi
class OrderStates(StatesGroup):
    WAITING_FOR_ADDRESS = State()

# .env faylidan muhit o'zgaruvchilarini yuklash
load_dotenv()

# 🔐 TOKEN va API URL'larni .env faylidan olish
API_TOKEN = os.getenv("API_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL", "http://127.0.0.1:8000")
USERS_ENDPOINT = os.getenv("USERS_ENDPOINT", "/api/users/bot-users")
CATEGORIES_ENDPOINT = os.getenv("CATEGORIES_ENDPOINT", "/api/products/categories/")
PRODUCTS_ENDPOINT = os.getenv("PRODUCTS_ENDPOINT", "/api/products/products/")
ORDER_GROUPS_ENDPOINT = os.getenv("ORDER_GROUPS_ENDPOINT", "/api/orders/order-groups/")
ORDERS_ENDPOINT = os.getenv("ORDERS_ENDPOINT", "/api/orders/orders/")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "398062629:TEST:999999999_F91D8F69C042267444B74CC0B3C747757EB0E065")

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Bot va Dispatcher'ni ishga tushirish
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# 🛒 Foydalanuvchi ma'lumotlari uchun saqlash
user_selected_product = {}
user_cart = {}
user_delivery_address = {}

def ensure_numeric_price(product_data):
    """Mahsulot narxini raqamli (float) formatga o'tkazish"""
    if isinstance(product_data.get('price'), str):
        try:
            product_data['price'] = float(product_data['price'])
        except (ValueError, TypeError):
            logging.warning(f"Mahsulot uchun noto'g'ri narx formati: {product_data.get('name', 'Nomalum')}")
            product_data['price'] = 0.0
    return product_data

# ▶️ /start buyrug'i
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Iltimos, buyurtma berish uchun telefon raqamingizni yuboring:", reply_markup=keyboard)

# ☎️ Kontakt ma'lumotlari
@dp.message(lambda message: message.contact)
async def contact_handler(message: types.Message):
    chat_id = str(message.chat.id)
    contact = message.contact
    logging.info(f"Kontakt qayta ishlanmoqda: chat_id={chat_id}, telefon={contact.phone_number}")

    photos = await bot.get_user_profile_photos(user_id=message.from_user.id, limit=1)
    photo_url = None
    if photos.total_count > 0:
        file_id = photos.photos[0][0].file_id
        file = await bot.get_file(file_id)
        photo_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file.file_path}"

    user_data = {
        "chat_id": chat_id,
        "first_name": message.chat.first_name or "Noma'lum",
        "last_name": message.chat.last_name or "",
        "username": message.chat.username or "",
        "platform": "telegram",
        "phone_number": contact.phone_number,
        "profile_photo_url": photo_url or "",
    }

    await message.answer("⏳ Ma'lumotlaringiz yuborilmoqda...")

    async with aiohttp.ClientSession() as session:
        try:
            check_url = f"{BASE_API_URL.rstrip('/')}{USERS_ENDPOINT.rstrip('/')}?chat_id={chat_id}"
            logging.info(f"Foydalanuvchi tekshirilmoqda: {check_url}")
            async with session.get(check_url) as check_response:
                response_text = await check_response.text()
                if check_response.status == 200:
                    existing_users = await check_response.json()
                    if existing_users:
                        logging.info(f"Foydalanuvchi topildi: chat_id={chat_id}, bot_user_id={existing_users[0]['id']}")
                        await send_categories(message)
                        return
                    else:
                        logging.info(f"Foydalanuvchi topilmadi: chat_id={chat_id}, yangi foydalanuvchi yaratilmoqda")
                else:
                    logging.error(f"Foydalanuvchi tekshirishda xato, status: {check_response.status}, javob: {response_text[:100]}...")
                    await message.answer(
                        f"❌ Foydalanuvchi tekshirishda xatolik, status kodi: {check_response.status}\n"
                        f"Iltimos, /start buyrug'ini qayta yuboring yoki administrator bilan bog'laning."
                    )
                    return

            post_url = f"{BASE_API_URL.rstrip('/')}{USERS_ENDPOINT.rstrip('/')}/"
            logging.info(f"Yangi foydalanuvchi yaratilmoqda: {post_url}")
            async with session.post(post_url, json=user_data) as response:
                response_text = await response.text()
                if response.status in (200, 201):
                    logging.info(f"Foydalanuvchi muvaffaqiyatli yaratildi: chat_id={chat_id}")
                    await message.answer("✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!")
                    await send_categories(message)
                else:
                    logging.error(f"Foydalanuvchi yaratishda xato, status: {response.status}, javob: {response_text[:100]}...")
                    await message.answer(
                        f"❌ Ro'yxatdan o'tishda xatolik, status kodi: {response.status}\n"
                        f"Iltimos, /start buyrug'ini qayta yuboring yoki administrator bilan bog'laning."
                    )
        except aiohttp.ClientError as e:
            logging.error(f"Foydalanuvchi ro'yxatdan o'tkazishda xato: {e}")
            await message.answer(
                f"⚠️ Server bilan aloqa xatosi:\n<code>{html.escape(str(e))}</code>\n"
                f"Iltimos, serveringiz ishlayotganligini tekshiring."
            )

# 📦 Kategoriyalarni yuborish
async def send_categories(message: types.Message):
    url = f"{BASE_API_URL.rstrip('/')}{CATEGORIES_ENDPOINT.rstrip('/')}/"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    categories = await response.json()
                    if not categories:
                        await message.answer("📭 Hech qanday kategoriya topilmadi.")
                        return

                    buttons = []
                    row = []
                    for cat in categories:
                        row.append(KeyboardButton(text=cat["name"]))
                        if len(row) == 2:
                            buttons.append(row)
                            row = []
                    if row:
                        buttons.append(row)
                    buttons.append([KeyboardButton(text="🛍 Savatchani ko'rish"), KeyboardButton(text="📜 Buyurtmalarim")])

                    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
                    await message.answer("📦 Kategoriya tanlang:", reply_markup=keyboard)
                else:
                    logging.error(f"Kategoriyalarni olishda xato, status: {response.status}")
                    await message.answer("❌ Kategoriyalarni olishda xatolik.")
        except aiohttp.ClientError as e:
            logging.error(f"Kategoriyalarni olishda xato: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 📂 Kategoriya tanlash
@dp.message(lambda message: message.text and message.text not in ["🛍 Savatchani ko'rish", "📜 Buyurtmalarim"])
async def category_selected_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    if not message.text:
        await message.answer("🚫 Iltimos, matnli xabar yuboring (masalan, kategoriya nomini).")
        return

    category_name = message.text.strip()

    async with aiohttp.ClientSession() as session:
        try:
            cat_url = f"{BASE_API_URL.rstrip('/')}{CATEGORIES_ENDPOINT.rstrip('/')}/"
            async with session.get(cat_url) as cat_resp:
                categories = await cat_resp.json()
                matched = next((c for c in categories if c["name"].lower() == category_name.lower()), None)

                if not matched:
                    await message.answer("🚫 Bunday kategoriya topilmadi.")
                    return

                prod_url = f"{BASE_API_URL.rstrip('/')}{PRODUCTS_ENDPOINT.rstrip('/')}/"
                async with session.get(prod_url) as prod_resp:
                    products = await prod_resp.json()
                    filtered = [p for p in products if p["category_name"].lower() == matched["name"].lower()]

                    if not filtered:
                        await message.answer("📭 Bu kategoriyada mahsulotlar yo'q.")
                        return

                    buttons = [
                        [InlineKeyboardButton(text=p["name"], callback_data=f"product_{p['id']}")]
                        for p in filtered
                    ]
                    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
                    await message.answer("🛍 Mahsulotlar:", reply_markup=markup)
        except aiohttp.ClientError as e:
            logging.error(f"Mahsulotlarni olishda xato: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# ✅ Mahsulot tanlash
@dp.callback_query(lambda c: c.data.startswith("product_"))
async def product_selected_callback(callback: types.CallbackQuery):
    product_id = callback.data.split("_")[1]
    user_id = str(callback.from_user.id)
    await callback.answer()

    async with aiohttp.ClientSession() as session:
        url = f"{BASE_API_URL.rstrip('/')}{PRODUCTS_ENDPOINT.rstrip('/')}/{product_id}/"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    product = await response.json()
                    product = ensure_numeric_price(product)
                    user_selected_product[user_id] = {"product": product, "quantity": 1}

                    caption = (
                        f"<b>📦 {product['name']}</b>\n"
                        f"💰 Narxi: <b>{product['price']}</b> so'm\n"
                        f"🗂 Kategoriya: {product['category_name']}\n"
                        f"🧮 Zaxira: {product['stock']} dona\n\n"
                        f"<i>{product['description'] or 'ℹ️ Tavsif mavjud emas'}</i>"
                    )

                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text="➖", callback_data="qty_decrease"),
                                InlineKeyboardButton(text="1 ta", callback_data="noop"),
                                InlineKeyboardButton(text="➕", callback_data="qty_increase")
                            ],
                            [InlineKeyboardButton(text="🛒 Savatchaga qo'shish", callback_data="add_to_cart")]
                        ]
                    )

                    fallback_image = "https://upload.wikimedia.org/wikipedia/commons/d/d1/Image_not_available.png"
                    image_url = product.get("image")
                    if not image_url or image_url.startswith(f"{BASE_API_URL}/"):
                        logging.warning(f"Mahsulot uchun standart rasm ishlatilmoqda: {product_id}, image_url: {image_url}")
                        await callback.message.answer_photo(photo=fallback_image, caption=caption, reply_markup=keyboard)
                    else:
                        await callback.message.answer_photo(photo=image_url, caption=caption, reply_markup=keyboard)
                else:
                    logging.error(f"Mahsulotni olishda xato: {product_id}, status: {response.status}")
                    await callback.message.answer("❌ Mahsulotni olishda xatolik.")
        except aiohttp.ClientError as e:
            logging.error(f"Mahsulotni olishda xato: {product_id}: {e}")
            await callback.message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 🔢 Miqdor yangilash
@dp.callback_query(lambda c: c.data in ["qty_increase", "qty_decrease"])
async def update_quantity_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    item = user_selected_product.get(user_id)

    if not item:
        await callback.answer("❌ Avval mahsulot tanlang.", show_alert=True)
        return

    qty = item["quantity"]
    if callback.data == "qty_increase":
        qty += 1
    elif callback.data == "qty_decrease" and qty > 1:
        qty -= 1

    item["quantity"] = qty
    product = item["product"]

    caption = (
        f"<b>📦 {product['name']}</b>\n"
        f"💰 Narxi: <b>{product['price']}</b> so'm\n"
        f"🗂 Kategoriya: {product['category_name']}\n"
        f"🧮 Zaxira: {product['stock']} dona\n\n"
        f"<i>{product['description'] or 'ℹ️ Tavsif mavjud emas'}</i>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➖", callback_data="qty_decrease"),
                InlineKeyboardButton(text=f"{qty} ta", callback_data="noop"),
                InlineKeyboardButton(text="➕", callback_data="qty_increase")
            ],
            [InlineKeyboardButton(text="🛒 Savatchaga qo'shish", callback_data="add_to_cart")]
        ]
    )

    try:
        await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
    except Exception as e:
        logging.warning(f"Tahrir qilishda xato: {e}")
        pass
    await callback.answer()

# ➕ Savatchaga qo'shish
@dp.callback_query(lambda c: c.data == "add_to_cart")
async def add_to_cart_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    item = user_selected_product.get(user_id)

    if not item:
        await callback.answer("❌ Avval mahsulot tanlang.", show_alert=True)
        return

    cart = user_cart.setdefault(user_id, {})
    product = item["product"]
    quantity = item["quantity"]

    if product["id"] in cart:
        cart[product["id"]]["quantity"] += quantity
    else:
        cart[product["id"]] = {"product": product, "quantity": quantity}

    await callback.answer(f"✅ {product['name']} dan {quantity} ta savatchaga qo'shildi.", show_alert=True)

# 🛍 Savatchani ko'rish
@dp.message(lambda message: message.text == "🛍 Savatchani ko'rish")
async def savatchani_korish_handler(message: types.Message):
    await show_cart(message)

async def show_cart(message: types.Message):
    user_id = str(message.from_user.id)
    cart = user_cart.get(user_id)

    if not cart:
        await message.answer("🧺 Savatchangiz hozircha bo'sh.")
        return

    text_lines = []
    total_price = 0.0
    for product_id, item in cart.items():
        product = item["product"]
        qty = item["quantity"]
        price = float(product["price"]) if isinstance(product["price"], str) else product["price"]
        subtotal = qty * price
        total_price += subtotal
        text_lines.append(
            f"<b>{product['name']}</b>\n"
            f"🔢 {qty} × {price:.2f} = <b>{subtotal:.2f} so'm</b>"
        )

    text = "\n\n".join(text_lines)
    text += f"\n\n<b>Umumiy narx: {total_price:.2f} so'm</b>"

    inline_keyboard = []
    for product_id in cart.keys():
        inline_keyboard.append(
            [InlineKeyboardButton(
                text=f"❌ {cart[product_id]['product']['name']} ni o'chirish",
                callback_data=f"remove_{product_id}"
            )]
        )

    inline_keyboard.append(
        [InlineKeyboardButton(text="📦 Buyurtma berish", callback_data="place_order")]
    )
    inline_keyboard.append(
        [InlineKeyboardButton(text="🔄 Savatchani tozalash", callback_data="clear_cart")]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer(text, reply_markup=keyboard)

# ❌ Savatchadan o'chirish
@dp.callback_query(lambda c: c.data.startswith("remove_"))
async def remove_from_cart_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    product_id = callback.data.split("_")[1]

    if user_id in user_cart and product_id in user_cart[user_id]:
        product_name = user_cart[user_id][product_id]["product"]["name"]
        del user_cart[user_id][product_id]

        await callback.message.answer(f"❌ {product_name} savatchadan o'chirildi.")
        await callback.answer()

        if not user_cart[user_id]:
            del user_cart[user_id]
            try:
                await callback.message.edit_text("🧺 Savatchangiz hozircha bo'sh.")
            except:
                await callback.message.answer("🧺 Savatchangiz hozircha bo'sh.")
        else:
            try:
                await show_cart_after_edit(callback.message)
            except Exception as e:
                logging.error(f"Savatchani yangilashda xato: {e}")
                await callback.message.answer(f"⚠️ Xatolik yuz berdi: {html.escape(str(e))}")
    else:
        await callback.answer("❌ Mahsulot topilmadi.", show_alert=True)

async def show_cart_after_edit(message: types.Message):
    user_id = str(message.from_user.id)
    cart = user_cart.get(user_id)

    if not cart:
        return

    text_lines = []
    total_price = 0.0
    for product_id, item in cart.items():
        product = item["product"]
        qty = item["quantity"]
        price = float(product["price"]) if isinstance(product["price"], str) else product["price"]
        subtotal = qty * price
        total_price += subtotal
        text_lines.append(
            f"<b>{product['name']}</b>\n"
            f"🔢 {qty} × {price:.2f} = <b>{subtotal:.2f} so'm</b>"
        )

    text = "\n\n".join(text_lines)
    text += f"\n\n<b>Umumiy narx: {total_price:.2f} so'm</b>"

    inline_keyboard = []
    for product_id in cart.keys():
        inline_keyboard.append(
            [InlineKeyboardButton(
                text=f"❌ {cart[product_id]['product']['name']} ni o'chirish",
                callback_data=f"remove_{product_id}"
            )]
        )

    inline_keyboard.append(
        [InlineKeyboardButton(text="📦 Buyurtma berish", callback_data="place_order")]
    )
    inline_keyboard.append(
        [InlineKeyboardButton(text="🔄 Savatchani tozalash", callback_data="clear_cart")]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Savatcha xabarini tahrir qilishda xato: {e}")
        await message.answer(text, reply_markup=keyboard)

# 🔄 Savatchani tozalash
@dp.callback_query(lambda c: c.data == "clear_cart")
async def clear_cart_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    if user_id in user_cart:
        del user_cart[user_id]
        await callback.answer("🧹 Savatcha tozalandi!", show_alert=True)
        try:
            await callback.message.edit_text("🧺 Savatchangiz hozircha bo'sh.")
        except:
            await callback.message.answer("🧺 Savatchangiz hozircha bo'sh.")
    else:
        await callback.answer("🧺 Savatchangiz allaqachon bo'sh.", show_alert=True)

# 📍 Buyurtma berish
@dp.callback_query(lambda c: c.data == "place_order")
async def place_order_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)
    cart = user_cart.get(user_id)

    if not cart or len(cart) == 0:
        await callback.answer("🧺 Savatchangiz bo'sh, buyurtma berish uchun mahsulot qo'shing.", show_alert=True)
        return

    await state.set_state(OrderStates.WAITING_FOR_ADDRESS)
    await callback.message.answer(
        "📍 Iltimos, yetkazib berish manzilini kiriting (masalan, shahar, ko'cha, uy raqami):"
    )
    await callback.answer()

# 📍 Yetkazib berish manzilini qayta ishlash
@dp.message(OrderStates.WAITING_FOR_ADDRESS)
async def delivery_address_handler(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    if user_id not in user_cart or not user_cart[user_id]:
        await message.answer("🧺 Savatchangiz bo'sh. Iltimos, mahsulot qo'shing.")
        await state.clear()
        await send_categories(message)
        return

    if not message.text:
        await message.answer("⚠️ Iltimos, matnli manzil kiriting.")
        return

    delivery_address = message.text.strip()
    if len(delivery_address) < 5:
        await message.answer("⚠️ Iltimos, to'liq manzil kiriting (kamida 5 ta belgi).")
        return

    user_delivery_address[user_id] = delivery_address
    logging.info(f"Manzil saqlandi: user_id={user_id}, manzil={delivery_address}")

    try:
        await message.answer(f"✅ Manzil saqlandi: {delivery_address}! Endi to'lovga o'tamiz...")
        await state.clear()
        await initiate_payment(message)
    except Exception as e:
        logging.error(f"To'lovni boshlashda xato: {e}")
        await message.answer(f"❌ To'lovni boshlashda xatolik yuz berdi: {html.escape(str(e))}. Iltimos, qayta urinib ko'ring.")
        await state.clear()

# 💳 To'lovni boshlash
async def initiate_payment(message: types.Message):
    user_id = str(message.from_user.id)
    cart = user_cart.get(user_id)
    if not cart:
        logging.error(f"Savatcha bo'sh: user_id={user_id}")
        await message.answer("🧺 Savatchangiz bo'sh.")
        return

    logging.info(f"To'lov jarayoni boshlanmoqda: user_id={user_id}, savatcha elementlari={len(cart)}")

    prices = []
    total_price = 0.0
    description = []
    for product_id, item in cart.items():
        product = item["product"]
        qty = item["quantity"]
        price = float(product["price"]) if isinstance(product["price"], str) else product["price"]

        if price <= 0:
            logging.error(f"Noto'g'ri narx: product_id={product_id}, price={price}")
            await message.answer(f"❌ Mahsulot '{product['name']}' narxi noto'g'ri ({price} so'm). Iltimos, administrator bilan bog'laning.")
            return

        subtotal = qty * price
        total_price += subtotal
        prices.append(LabeledPrice(label=f"{product['name']} ({qty} ta)", amount=int(subtotal * 100)))
        description.append(f"{product['name']} - {qty} ta x {price:.2f} so'm")

    if total_price <= 0:
        logging.error(f"Umumiy narx noto'g'ri: total_price={total_price}, user_id={user_id}")
        await message.answer("❌ Buyurtma narxi noto'g'ri. Iltimos, savatchangizni tekshiring.")
        return

    logging.info(f"To'lov ma'lumotlari: user_id={user_id}, total_price={total_price:.2f}, items={description}")

    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="Buyurtma To'lovi",
            description="\n".join(description),
            payload=f"order_{user_id}_{int(asyncio.get_event_loop().time())}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency="UZS",
            prices=prices
        )
        logging.info(f"Hisob-faktura yuborildi: user_id={user_id}")
    except Exception as e:
        logging.error(f"Hisob-faktura yuborishda xato: {str(e)}")
        await message.answer(
            f"❌ To'lovni boshlashda xatolik yuz berdi:\n"
            f"<code>{html.escape(str(e))}</code>\n"
            f"Iltimos, qayta urinib ko'ring yoki administrator bilan bog'laning."
        )

# ✅ Oldindan tekshirish so'rovi
@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# 💵 Muvaffaqiyatli to'lov
@dp.message(lambda message: message.successful_payment)
async def successful_payment_handler(message: types.Message):
    user_id = str(message.from_user.id)
    cart = user_cart.get(user_id)
    delivery_address = user_delivery_address.get(user_id)

    if not cart or not delivery_address:
        logging.error(f"Buyurtma yoki manzil topilmadi: user_id={user_id}, cart={cart}, delivery_address={delivery_address}")
        await message.answer("❌ Buyurtma yoki manzil topilmadi. Iltimos, qayta urinib ko'ring.")
        return

    total_amount = message.successful_payment.total_amount / 100
    order_id = message.successful_payment.invoice_payload
    logging.info(f"To'lov muvaffaqiyatli: user_id={user_id}, order_id={order_id}, total_amount={total_amount}, manzil={delivery_address}")

    async with aiohttp.ClientSession() as session:
        try:
            # Foydalanuvchi tekshiruvi
            user_url = f"{BASE_API_URL.rstrip('/')}{USERS_ENDPOINT.rstrip('/')}?chat_id={user_id}"
            logging.info(f"Foydalanuvchi tekshirilmoqda: {user_url}")
            async with session.get(user_url) as resp:
                response_text = await resp.text()
                if resp.status != 200:
                    logging.error(f"BotUser'ni olishda xato, status: {resp.status}, javob: {response_text}")
                    await message.answer(
                        f"❌ Server xatosi: Foydalanuvchi topilmadi, status kodi: {resp.status}."
                    )
                    return
                data = await resp.json()
                if not data or len(data) != 1:
                    logging.error(f"Chat_id uchun noto'g'ri BotUser ma'lumotlari: {user_id}: {data}")
                    await message.answer(
                        "❌ Ro'yxatdan o'tmagansiz yoki foydalanuvchi ma'lumotlari xato."
                    )
                    return
                bot_user_id = data[0]["id"]
                logging.info(f"Bot_user_id olindi: {bot_user_id}, chat_id: {user_id}")

            # OrderGroup yaratish
            order_group_data = {
                "bot_user": bot_user_id,
                "is_paid": True,
                "status": "active",
                "delivery_address": delivery_address,
                "total_price": float(total_amount)
            }
            order_group_url = f"{BASE_API_URL.rstrip('/')}{ORDER_GROUPS_ENDPOINT.rstrip('/')}/"
            logging.info(f"OrderGroup yaratilmoqda: {order_group_url}, ma'lumotlar: {order_group_data}")
            async with session.post(order_group_url, json=order_group_data) as response:
                response_text = await response.text()
                if response.status != 201:
                    logging.error(f"OrderGroup yaratishda xato, status: {response.status}, javob: {response_text}")
                    await message.answer(
                        f"❌ Buyurtma guruhini yaratishda xatolik, status kodi: {response.status}\n"
                        f"Javob: {response_text[:200]}\n"
                        f"Iltimos, administrator bilan bog'laning."
                    )
                    return
                order_group = await response.json()
                order_group_id = order_group["id"]
                saved_address = order_group.get("delivery_address", "Manzil topilmadi")
                logging.info(f"OrderGroup yaratildi: ID={order_group_id}, bot_user_id={bot_user_id}, manzil={saved_address}")
                if saved_address != delivery_address:
                    logging.warning(f"Manzil saqlanmadi: kutilgan={delivery_address}, saqlangan={saved_address}")

            # Orderlarni yaratish
            success = True
            for product_id, item in cart.items():
                order_data = {
                    "order_group": order_group_id,
                    "product": int(product_id),
                    "quantity": max(1, item["quantity"]),
                    "subtotal": float(item["quantity"] * item["product"]["price"])
                }
                logging.info(f"Order yaratilmoqda: product_id={product_id}, order_data={order_data}")
                try:
                    async with session.post(f"{BASE_API_URL.rstrip('/')}{ORDERS_ENDPOINT.rstrip('/')}/", json=order_data) as response:
                        response_text = await response.text()
                        if response.status != 201:
                            logging.error(f"Mahsulot uchun buyurtma yaratishda xato: {product_id}, status: {response.status}, javob: {response_text}")
                            success = False
                            await message.answer(
                                f"❌ Buyurtma qo'shishda xatolik, mahsulot ID: {product_id}, status kodi: {response.status}\n"
                                f"Javob: {response_text[:200]}\n"
                                f"Iltimos, administrator bilan bog'laning."
                            )
                            break
                        order_response = await response.json()
                        logging.info(f"Buyurtma yaratildi: product_id={product_id}, order_group_id={order_group_id}, order_id={order_response.get('id')}")
                except aiohttp.ClientError as e:
                    logging.error(f"Mahsulot uchun buyurtma yaratishda xato: {product_id}: {e}")
                    success = False
                    await message.answer(
                        f"⚠️ Tarmoq xatosi mahsulot ID {product_id} uchun:\n<code>{html.escape(str(e))}</code>"
                    )
                    break

            if success:
                # Buyurtma muvaffaqiyatli saqlanganda savatcha va manzilni tozalash
                del user_cart[user_id]
                del user_delivery_address[user_id]
                await message.answer(
                    f"✅ Buyurtmangiz muvaffaqiyatli qabul qilindi!\n"
                    f"To'lov: {total_amount:.2f} so'm\n"
                    f"Yetkazib berish manzili: {delivery_address}\n"
                    f"📜 Buyurtmalaringizni ko'rish uchun 'Buyurtmalarim' tugmasini bosing."
                )
                # Backenddan yaratilgan buyurtmani qayta tekshirish
                check_url = f"{BASE_API_URL.rstrip('/')}{ORDER_GROUPS_ENDPOINT.rstrip('/')}?chat_id={user_id}"
                async with session.get(check_url) as check_response:
                    check_text = await check_response.text()
                    if check_response.status == 200:
                        orders = await check_response.json()
                        logging.info(f"Backenddan buyurtma tekshirildi: user_id={user_id}, buyurtmalar={orders}")
                        for order in orders:
                            if order["id"] == order_group_id:
                                logging.info(f"Tekshirilgan OrderGroup: ID={order_group_id}, manzil={order.get('delivery_address', 'Manzil topilmadi')}")
                    else:
                        logging.error(f"Buyurtma tekshirishda xato: status={check_response.status}, javob={check_text}")
            else:
                await message.answer("⚠️ Buyurtma to'liq qayta ishlanmadi. Iltimos, administrator bilan bog'laning.")
        except aiohttp.ClientError as e:
            logging.error(f"Buyurtma yaratishda xato: {e}")
            await message.answer(
                f"⚠️ Tarmoq xatosi:\n<code>{html.escape(str(e))}</code>"
            )

# 📜 Buyurtmalar ro'yxati
@dp.message(lambda message: message.text == "📜 Buyurtmalarim")
async def orders_handler(message: types.Message):
    user_id = str(message.from_user.id)
    logging.info(f"Buyurtmalar olinmoqda: chat_id={user_id}")

    async with aiohttp.ClientSession() as session:
        try:
            user_url = f"{BASE_API_URL.rstrip('/')}{USERS_ENDPOINT.rstrip('/')}?chat_id={user_id}"
            logging.info(f"Foydalanuvchi tekshirilmoqda: {user_url}")
            async with session.get(user_url) as user_resp:
                response_text = await user_resp.text()
                if user_resp.status != 200:
                    logging.error(f"BotUser'ni olishda xato, status: {user_resp.status}, javob: {response_text}")
                    await message.answer(f"❌ Foydalanuvchi ma'lumotlarini olishda xatolik, status kodi: {user_resp.status}.")
                    return
                user_data = await user_resp.json()
                if not user_data or len(user_data) != 1:
                    logging.error(f"Chat_id uchun BotUser topilmadi yoki bir nechta: {user_id}: {user_data}")
                    await message.answer(
                        "❌ Ro'yxatdan o'tmagansiz. Iltimos, /start buyrug'ini yuboring."
                    )
                    return
                bot_user_id = user_data[0]["id"]
                logging.info(f"BotUser ID: {bot_user_id}, chat_id: {user_id}")

            url = f"{BASE_API_URL.rstrip('/')}{ORDER_GROUPS_ENDPOINT.rstrip('/')}?chat_id={user_id}"
            logging.info(f"OrderGroups so'rovi: {url}")
            async with session.get(url) as response:
                response_text = await response.text()
                if response.status == 200:
                    order_groups = await response.json()
                    logging.info(f"OrderGroups javobi: {order_groups}")
                    if not order_groups:
                        await message.answer("📭 Hozircha buyurtmalaringiz yo'q.")
                        return

                    text_lines = []
                    for group in order_groups:
                        group_id = group.get("id")
                        total_price = float(group.get("total_price", "0")) if group.get("total_price") else 0.0
                        delivery_address = group.get("delivery_address", "Manzil kiritilmagan")
                        group_text = [f"<b>Buyurtma guruh ID: {group_id}</b>"]

                        orders = group.get("orders", [])
                        for order in orders:
                            product_id = order.get("product")
                            quantity = order.get("quantity", 0)
                            subtotal = float(order.get("subtotal", "0")) if order.get("subtotal") else 0.0

                            async with session.get(f"{BASE_API_URL.rstrip('/')}{PRODUCTS_ENDPOINT.rstrip('/')}/{product_id}/") as prod_resp:
                                response_text = await prod_resp.text()
                                if prod_resp.status == 200:
                                    product = await prod_resp.json()
                                    product_name = product.get("name", "Noma'lum mahsulot")
                                    price = float(product.get("price", "0")) if product.get("price") else 0.0
                                else:
                                    logging.error(f"Mahsulotni olishda xato: {product_id}, status: {prod_resp.status}, javob: {response_text}")
                                    product_name = "Noma'lum mahsulot"
                                    price = 0.0

                            group_text.append(
                                f"  📦 {product_name}\n"
                                f"  🔢 Miqdor: {quantity} ta\n"
                                f"  💰 Narxi: {price:.2f} so'm\n"
                                f"  📊 Jami: {subtotal:.2f} so'm"
                            )

                        is_paid = "To'langan" if group.get("is_paid", False) else "To'lanmagan"
                        status = {
                            "active": "Faol",
                            "delivered": "Yetkazib berilgan",
                            "cancelled": "Bekor qilingan"
                        }.get(group.get("status"), "Noma'lum")
                        group_text.append(
                            f"📍 Yetkazib berish manzili: {delivery_address}\n"
                            f"💳 To'lov holati: {is_paid}\n"
                            f"📦 Holati: {status}\n"
                            f"📊 Umumiy narx: {total_price:.2f} so'm"
                        )
                        text_lines.append("\n".join(group_text))

                    text = "\n\n".join(text_lines)
                    await message.answer(f"📜 Buyurtmalaringiz:\n\n{text}")
                else:
                    logging.error(f"OrderGroups'ni olishda xato, status: {response.status}, javob: {response_text}")
                    await message.answer(f"❌ Buyurtmalarni olishda xatolik, status kodi: {response.status}, javob: {response_text[:200]}")
        except aiohttp.ClientError as e:
            logging.error(f"Buyurtmalarni olishda xato: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 🔃 Botni ishga tushirish
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())