import asyncio
import logging
import html
import aiohttp
from dotenv import load_dotenv
import os

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties

# Load environment variables from .env file
load_dotenv()

# 🔐 TOKEN and API URLs from .env
API_TOKEN = os.getenv("API_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")
USERS_ENDPOINT = os.getenv("USERS_ENDPOINT")
CATEGORIES_ENDPOINT = os.getenv("CATEGORIES_ENDPOINT")
PRODUCTS_ENDPOINT = os.getenv("PRODUCTS_ENDPOINT")
ORDER_GROUPS_ENDPOINT = os.getenv("ORDER_GROUPS_ENDPOINT")
ORDERS_ENDPOINT = os.getenv("ORDERS_ENDPOINT")

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize bot and dispatcher
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# 🛒 User data storage
user_selected_product = {}
user_cart = {}

def ensure_numeric_price(product_data):
    """Ensure product price is numeric (float)"""
    if isinstance(product_data.get('price'), str):
        try:
            product_data['price'] = float(product_data['price'])
        except (ValueError, TypeError):
            logging.warning(f"Invalid price format for product: {product_data.get('name', 'Unknown')}")
            product_data['price'] = 0.0
    return product_data

# ▶️ /start
@dp.message(F.text == "/start")
async def start_handler(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Iltimos, buyurtma berish uchun telefon raqamingizni yuboring:", reply_markup=keyboard)

# ☎️ Contact handler
@dp.message(F.contact)
async def contact_handler(message: types.Message):
    chat_id = str(message.chat.id)
    contact = message.contact
    logging.info(f"Processing contact for chat_id: {chat_id}, phone: {contact.phone_number}")

    photos = await bot.get_user_profile_photos(user_id=message.from_user.id, limit=1)
    photo_url = None
    if photos.total_count > 0:
        file_id = photos.photos[0][0].file_id
        file = await bot.get_file(file_id)
        photo_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file.file_path}"

    user_data = {
        "chat_id": chat_id,
        "first_name": message.chat.first_name or "Unknown",
        "last_name": message.chat.last_name or "",
        "username": message.chat.username or "",
        "platform": "telegram",
        "phone_number": contact.phone_number,
        "profile_photo_url": photo_url or "",
    }

    await message.answer("⏳ Ma'lumotlaringiz yuborilmoqda...")

    async with aiohttp.ClientSession() as session:
        try:
            # Check if user exists
            check_url = f"{BASE_API_URL}{USERS_ENDPOINT}?chat_id={chat_id}"
            async with session.get(check_url) as check_response:
                if check_response.status == 200:
                    existing_users = await check_response.json()
                    if existing_users:
                        logging.info(f"User found for chat_id: {chat_id}, bot_user_id: {existing_users[0]['id']}")
                        await send_categories(message)
                        return
                    else:
                        logging.info(f"No user found for chat_id: {chat_id}, creating new user")

            # Create new user
            async with session.post(f"{BASE_API_URL}{USERS_ENDPOINT}", json=user_data) as response:
                response_text = await response.text()
                if response.status in (200, 201):
                    logging.info(f"User created successfully: chat_id={chat_id}")
                    await message.answer("✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!")
                    await send_categories(message)
                else:
                    logging.error(f"Failed to create user, status: {response.status}, response: {response_text}")
                    await message.answer(
                        f"❌ Ro'yxatdan o'tishda xatolik, status kodi: {response.status}\n"
                        f"Server javobi: <code>{html.escape(response_text)}</code>\n"
                        f"Iltimos, /start buyrug'ini qayta yuboring yoki administrator bilan bog'laning."
                    )
        except aiohttp.ClientError as e:
            logging.error(f"Error during user registration: {e}")
            await message.answer(
                f"⚠️ Server bilan aloqa xatosi:\n<code>{html.escape(str(e))}</code>\n"
                f"Iltimos, serveringiz ishlayotganligini tekshiring."
            )

# 📦 Send categories
async def send_categories(message: types.Message):
    url = f"{BASE_API_URL}{CATEGORIES_ENDPOINT}"
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
                    logging.error(f"Failed to fetch categories, status: {response.status}")
                    await message.answer("❌ Kategoriyalarni olishda xatolik.")
        except aiohttp.ClientError as e:
            logging.error(f"Error fetching categories: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 📂 Category selection handler
@dp.message()
async def category_selected_handler(message: types.Message):
    if message.text == "🛍 Savatchani ko'rish":
        await savatchani_korish_handler(message)
        return
    if message.text == "📜 Buyurtmalarim":
        await orders_handler(message)
        return

    category_name = message.text.strip()

    async with aiohttp.ClientSession() as session:
        try:
            cat_url = f"{BASE_API_URL}{CATEGORIES_ENDPOINT}"
            async with session.get(cat_url) as cat_resp:
                categories = await cat_resp.json()
                matched = next((c for c in categories if c["name"].lower() == category_name.lower()), None)

                if not matched:
                    await message.answer("🚫 Bunday kategoriya topilmadi.")
                    return

                prod_url = f"{BASE_API_URL}{PRODUCTS_ENDPOINT}"
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
            logging.error(f"Error fetching products: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# ✅ Product selection
@dp.callback_query(F.data.startswith("product_"))
async def product_selected_callback(callback: types.CallbackQuery):
    product_id = callback.data.split("_")[1]
    user_id = str(callback.from_user.id)
    await callback.answer()

    async with aiohttp.ClientSession() as session:
        url = f"{BASE_API_URL}{PRODUCTS_ENDPOINT}{product_id}/"
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
                        logging.warning(f"Using fallback image for product {product_id}, image_url: {image_url}")
                        await callback.message.answer_photo(photo=fallback_image, caption=caption, reply_markup=keyboard)
                    else:
                        await callback.message.answer_photo(photo=image_url, caption=caption, reply_markup=keyboard)
                else:
                    logging.error(f"Failed to fetch product {product_id}, status: {response.status}")
                    await callback.message.answer("❌ Mahsulotni olishda xatolik.")
        except aiohttp.ClientError as e:
            logging.error(f"Error fetching product {product_id}: {e}")
            await callback.message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 🔢 Quantity update
@dp.callback_query(F.data.in_(["qty_increase", "qty_decrease"]))
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
        logging.warning(f"Failed to edit caption: {e}")
        pass
    await callback.answer()

# ➕ Add to cart
@dp.callback_query(F.data == "add_to_cart")
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

# 🛍 Show cart
@dp.message(F.text == "🛍 Savatchani ko'rish")
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
            f"🔢 {qty} × {price} = <b>{subtotal:.2f} so'm</b>"
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

# ❌ Remove from cart
@dp.callback_query(F.data.startswith("remove_"))
async def remove_from_cart_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    product_id = int(callback.data.split("_")[1])

    if user_id in user_cart and product_id in user_cart[user_id]:
        product_name = user_cart[user_id][product_id]["product"]["name"]
        del user_cart[user_id][product_id]

        await callback.message.answer(f"❌ {product_name} savatchadan o'chirildi.")
        await callback.answer()

        if not user_cart[user_id]:
            del user_cart[user_id]
        else:
            try:
                await show_cart_after_edit(callback.message)
            except Exception as e:
                logging.error(f"Error updating cart display: {e}")
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
            f"🔢 {qty} × {price} = <b>{subtotal:.2f} so'm</b>"
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
        logging.error(f"Error editing cart message: {e}")
        await message.answer(text, reply_markup=keyboard)

# 🔄 Clear cart
@dp.callback_query(F.data == "clear_cart")
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

# 📦 Place order
@dp.callback_query(F.data == "place_order")
async def place_order_callback(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    cart = user_cart.get(user_id)

    if not cart or len(cart) == 0:
        await callback.answer("🧺 Savatchangiz bo'sh, buyurtma berish uchun mahsulot qo'shing.", show_alert=True)
        return

    async with aiohttp.ClientSession() as session:
        try:
            # Fetch BotUser by chat_id
            url = f"{BASE_API_URL}{USERS_ENDPOINT}?chat_id={user_id}"
            async with session.get(url) as resp:
                response_text = await resp.text()
                if resp.status != 200:
                    logging.error(f"Failed to fetch BotUser, status: {resp.status}, response: {response_text}")
                    await callback.answer(
                        f"❌ Server xatosi: Foydalanuvchi topilmadi, status kodi: {resp.status}. "
                        f"Iltimos, /start buyrug'ini qayta yuboring.",
                        show_alert=True
                    )
                    return
                data = await resp.json()
                if not data or len(data) != 1:
                    logging.error(f"Invalid BotUser data for chat_id {user_id}: {data}")
                    await callback.answer(
                        "❌ Ro'yxatdan o'tmagansiz yoki foydalanuvchi ma'lumotlari xato. "
                        "Iltimos, /start buyrug'ini yuboring.",
                        show_alert=True
                    )
                    return
                bot_user_id = data[0]["id"]
                logging.info(f"Fetched bot_user_id: {bot_user_id} for chat_id: {user_id}")

            # Create OrderGroup
            order_group_data = {
                "bot_user": bot_user_id,
                "is_paid": False,
                "status": "active"
            }
            async with session.post(f"{BASE_API_URL}{ORDER_GROUPS_ENDPOINT}", json=order_group_data) as response:
                response_text = await response.text()
                if response.status != 201:
                    logging.error(f"Failed to create OrderGroup, status: {response.status}, response: {response_text}")
                    await callback.message.answer(
                        f"❌ Buyurtma guruhini yaratishda xatolik, status kodi: {response.status}\n"
                        f"Server javobi: <code>{html.escape(response_text)}</code>\n"
                        f"Iltimos, administrator bilan bog'laning."
                    )
                    return
                order_group = await response.json()
                order_group_id = order_group["id"]
                logging.info(f"Created OrderGroup ID: {order_group_id} for bot_user_id: {bot_user_id}")

            # Create Orders
            success = True
            for product_id, item in cart.items():
                order_data = {
                    "order_group": order_group_id,
                    "product": int(product_id),
                    "quantity": max(1, item["quantity"])
                }
                try:
                    async with session.post(f"{BASE_API_URL}{ORDERS_ENDPOINT}", json=order_data) as response:
                        response_text = await response.text()
                        if response.status != 201:
                            logging.error(f"Failed to create Order for product {product_id}, status: {response.status}, response: {response_text}")
                            success = False
                            await callback.message.answer(
                                f"❌ Buyurtma qo'shishda xatolik, status kodi: {response.status}\n"
                                f"Server javobi: <code>{html.escape(response_text)}</code>\n"
                                f"Iltimos, administrator bilan bog'laning."
                            )
                            break
                        logging.info(f"Created Order for product_id: {product_id}, order_group_id: {order_group_id}")
                except aiohttp.ClientError as e:
                    logging.error(f"Error creating Order for product {product_id}: {e}")
                    success = False
                    await callback.message.answer(
                        f"⚠️ Tarmoq xatosi:\n<code>{html.escape(str(e))}</code>\n"
                        f"Iltimos, serveringiz ishlayotganligini tekshiring."
                    )
                    break

            if success:
                del user_cart[user_id]
                await callback.answer("✅ Buyurtmangiz muvaffaqiyatli qabul qilindi!", show_alert=True)
                try:
                    await callback.message.edit_text("🧺 Savatchangiz hozircha bo'sh.")
                except:
                    await callback.message.answer("🧺 Savatchangiz hozircha bo'sh.")
        except aiohttp.ClientError as e:
            logging.error(f"Error during order creation: {e}")
            await callback.message.answer(
                f"⚠️ Tarmoq xatosi:\n<code>{html.escape(str(e))}</code>\n"
                f"Iltimos, serveringiz ishlayotganligini tekshiring."
            )

# 📜 Orders handler
@dp.message(F.text == "📜 Buyurtmalarim")
async def orders_handler(message: types.Message):
    user_id = str(message.from_user.id)
    logging.info(f"Fetching orders for chat_id: {user_id}")

    async with aiohttp.ClientSession() as session:
        try:
            # Fetch BotUser to verify existence
            user_url = f"{BASE_API_URL}{USERS_ENDPOINT}?chat_id={user_id}"
            async with session.get(user_url) as user_resp:
                if user_resp.status != 200:
                    logging.error(f"Failed to fetch BotUser, status: {user_resp.status}")
                    await message.answer("❌ Foydalanuvchi ma'lumotlarini olishda xatolik.")
                    return
                user_data = await user_resp.json()
                if not user_data or len(user_data) != 1:
                    logging.error(f"No or multiple BotUsers found for chat_id: {user_id}")
                    await message.answer(
                        "❌ Ro'yxatdan o'tmagansiz. Iltimos, /start buyrug'ini yuboring."
                    )
                    return
                bot_user_id = user_data[0]["id"]
                logging.info(f"BotUser ID: {bot_user_id} for chat_id: {user_id}")

            # Fetch OrderGroups
            url = f"{BASE_API_URL}{ORDER_GROUPS_ENDPOINT}?chat_id={user_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    order_groups = await response.json()
                    if not order_groups:
                        await message.answer("📭 Hozircha buyurtmalaringiz yo'q.")
                        return

                    text_lines = []
                    for group in order_groups:
                        group_id = group.get("id")
                        total_price = float(group.get("total_price", "0")) if group.get("total_price") else 0.0
                        group_text = [f"<b>Buyurtma guruh ID: {group_id}</b>"]

                        orders = group.get("orders", [])
                        for order in orders:
                            product_id = order.get("product", 0)
                            quantity = order.get("quantity", 0)
                            subtotal = float(order.get("subtotal", "0")) if order.get("subtotal") else 0.0

                            async with session.get(f"{BASE_API_URL}{PRODUCTS_ENDPOINT}{product_id}/") as prod_resp:
                                if prod_resp.status == 200:
                                    product = await prod_resp.json()
                                    product_name = product.get("name", "Noma'lum mahsulot")
                                    price = float(product.get("price", "0")) if product.get("price") else 0.0
                                else:
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
                            f"💳 To'lov holati: {is_paid}\n"
                            f"📦 Holati: {status}\n"
                            f"📊 Umumiy narx: {total_price:.2f} so'm"
                        )
                        text_lines.append("\n".join(group_text))

                    text = "\n\n".join(text_lines)
                    await message.answer(f"📜 Buyurtmalaringiz:\n\n{text}")
                else:
                    logging.error(f"Failed to fetch OrderGroups, status: {response.status}")
                    await message.answer(f"❌ Buyurtmalarni olishda xatolik, status kodi: {response.status}")
        except aiohttp.ClientError as e:
            logging.error(f"Error fetching orders: {e}")
            await message.answer(f"⚠️ Xatolik:\n<code>{html.escape(str(e))}</code>")

# 🔃 Run the bot
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))