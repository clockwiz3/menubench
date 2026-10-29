"""Hand-written vocabulary for synthetic menus. Kept as plain data so the generator stays deterministic."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectionVocab:
    title: str
    bases: tuple[str, ...]
    modifiers: tuple[str, ...] = ()
    ingredients: tuple[str, ...] = ()
    price_factor: float = 1.0  # relative to the venue price band
    sizes: tuple[tuple[str, ...], ...] = ()  # alternative size label sets; empty means single price


@dataclass(frozen=True)
class VenueVocab:
    titles: tuple[str, ...]
    sections: tuple[str, ...]
    band: tuple[float, float]  # base price range in the venue currency
    notes: tuple[str, ...] = field(default=())


RU_SECTIONS: dict[str, SectionVocab] = {
    "breakfast": SectionVocab(
        "Завтраки",
        ("Сырники", "Омлет", "Каша овсяная", "Яичница", "Блины", "Скрэмбл", "Гранола", "Драники", "Шакшука"),
        ("со сметаной", "с ветчиной", "с ягодами", "с лососем", "по-домашнему", "с грибами", "с сыром"),
        ("сметана", "мёд", "ягоды", "зелень", "томаты", "сыр", "бекон", "шпинат", "авокадо"),
        0.8,
    ),
    "salads": SectionVocab(
        "Салаты",
        ("Цезарь", "Греческий", "Оливье", "Винегрет", "Салат с тунцом", "Нисуаз", "Салат с печёной свёклой"),
        ("с курицей", "с креветками", "с лососем", "классический", "с моцареллой"),
        ("романо", "пармезан", "томаты черри", "огурец", "фета", "маслины", "киноа", "руккола"),
        1.0,
    ),
    "soups": SectionVocab(
        "Супы",
        (
            "Борщ",
            "Солянка",
            "Том ям",
            "Крем-суп тыквенный",
            "Уха",
            "Куриный суп",
            "Щи",
            "Харчо",
            "Рассольник",
        ),
        ("с говядиной", "сборная", "с креветками", "по-домашнему", "с лапшой", "с пампушками"),
        ("сметана", "зелень", "лимон", "чеснок", "гренки", "кокосовое молоко"),
        0.8,
    ),
    "mains": SectionVocab(
        "Горячее",
        (
            "Котлета",
            "Бефстроганов",
            "Плов",
            "Стейк",
            "Куриное филе",
            "Судак",
            "Голубцы",
            "Пельмени",
            "Вареники",
        ),
        ("с пюре", "с гречкой", "на гриле", "в сливочном соусе", "по-киевски", "с овощами", "домашние"),
        ("картофель", "гречка", "грибы", "лук", "сливки", "овощи гриль", "рис", "сметана"),
        1.5,
    ),
    "pasta": SectionVocab(
        "Паста",
        ("Карбонара", "Болоньезе", "Паста с морепродуктами", "Фетучини", "Лазанья", "Песто", "Арабьята"),
        ("с беконом", "с курицей и грибами", "классическая", "со шпинатом"),
        ("пармезан", "сливки", "бекон", "базилик", "томаты", "чеснок", "креветки"),
        1.3,
    ),
    "pizza": SectionVocab(
        "Пицца",
        ("Маргарита", "Пепперони", "Четыре сыра", "Гавайская", "Мясная", "Диабло", "Грибная", "Барбекю"),
        (),
        ("моцарелла", "томатный соус", "пепперони", "ананас", "шампиньоны", "халапеньо", "бекон"),
        1.4,
        (("25 см", "30 см", "35 см"), ("S", "M", "L"), ("Малая", "Средняя", "Большая")),
    ),
    "burgers": SectionVocab(
        "Бургеры",
        (
            "Чизбургер",
            "Бургер классический",
            "Чикен бургер",
            "Бургер с беконом",
            "Двойной бургер",
            "Вегги бургер",
        ),
        ("острый", "с халапеньо", "BBQ", "с грибами"),
        ("говядина", "чеддер", "бекон", "соус BBQ", "маринованный огурец", "салат айсберг", "томаты"),
        1.0,
    ),
    "snacks": SectionVocab(
        "Закуски",
        (
            "Картофель фри",
            "Наггетсы",
            "Луковые кольца",
            "Сырные палочки",
            "Крылья",
            "Картофель по-деревенски",
        ),
        ("с соусом", "острые", "большая порция"),
        ("сырный соус", "кетчуп", "чесночный соус", "барбекю"),
        0.5,
    ),
    "sides": SectionVocab(
        "Гарниры",
        ("Пюре картофельное", "Гречка", "Рис отварной", "Макароны", "Овощи на пару", "Картофель жареный"),
        ("с маслом", "с луком", "с зеленью"),
        (),
        0.4,
    ),
    "desserts": SectionVocab(
        "Десерты",
        ("Чизкейк", "Тирамису", "Медовик", "Наполеон", "Брауни", "Панна котта", "Эклер", "Мороженое"),
        ("Нью-Йорк", "классический", "шоколадный", "с ягодным соусом", "домашний"),
        ("сливочный сыр", "маскарпоне", "ягоды", "шоколад", "карамель", "мёд"),
        0.7,
    ),
    "drinks": SectionVocab(
        "Напитки",
        ("Морс клюквенный", "Лимонад", "Компот", "Сок апельсиновый", "Чай чёрный", "Чай зелёный", "Вода"),
        ("домашний", "свежевыжатый", "в чайнике", "газированная", "негазированная"),
        (),
        0.4,
    ),
    "coffee": SectionVocab(
        "Кофе",
        ("Эспрессо", "Американо", "Капучино", "Латте", "Флэт уайт", "Раф", "Какао", "Моккачино"),
        ("ванильный", "на овсяном молоке", "солёная карамель", "классический"),
        (),
        1.0,
        (("250 мл", "350 мл", "450 мл"), ("S", "M", "L"), ("0,25", "0,35", "0,45")),
    ),
    "bakery": SectionVocab(
        "Выпечка",
        ("Круассан", "Синнабон", "Маффин", "Пирожок", "Слойка", "Сэндвич", "Киш"),
        ("с миндалём", "с вишней", "с ветчиной и сыром", "шоколадный", "с капустой"),
        (),
        0.8,
    ),
}

EN_SECTIONS: dict[str, SectionVocab] = {
    "breakfast": SectionVocab(
        "Breakfast",
        ("Pancakes", "Omelette", "Eggs Benedict", "French Toast", "Oatmeal", "Breakfast Burrito", "Waffles"),
        ("with Bacon", "with Berries", "Classic", "with Smoked Salmon", "Western", "Buttermilk"),
        ("maple syrup", "berries", "bacon", "spinach", "avocado", "hollandaise", "cheddar", "sourdough"),
        0.9,
    ),
    "salads": SectionVocab(
        "Salads",
        (
            "Caesar Salad",
            "Greek Salad",
            "Cobb Salad",
            "Garden Salad",
            "Caprese",
            "Kale Salad",
            "Tuna Nicoise",
        ),
        ("with Chicken", "with Shrimp", "with Salmon", "House"),
        ("romaine", "parmesan", "cherry tomatoes", "cucumber", "feta", "olives", "croutons", "quinoa"),
        1.0,
    ),
    "soups": SectionVocab(
        "Soups",
        ("Tomato Soup", "Clam Chowder", "Chicken Noodle Soup", "French Onion", "Minestrone", "Lentil Soup"),
        ("Cup", "Bowl", "Creamy", "Homestyle"),
        ("basil", "cream", "croutons", "gruyere", "vegetables"),
        0.7,
    ),
    "mains": SectionVocab(
        "Entrees",
        (
            "Ribeye Steak",
            "Grilled Salmon",
            "Roast Chicken",
            "Fish and Chips",
            "Meatloaf",
            "Pork Chop",
            "Short Ribs",
        ),
        ("with Mashed Potatoes", "with Grilled Vegetables", "Cajun", "Herb Roasted", "BBQ"),
        ("potatoes", "green beans", "gravy", "lemon butter", "coleslaw", "rice pilaf"),
        1.6,
    ),
    "pasta": SectionVocab(
        "Pasta",
        (
            "Spaghetti Carbonara",
            "Fettuccine Alfredo",
            "Penne Arrabbiata",
            "Lasagna",
            "Mac and Cheese",
            "Pesto",
        ),
        ("with Chicken", "with Shrimp", "Classic", "Baked"),
        ("parmesan", "cream", "pancetta", "basil", "garlic", "tomato sauce"),
        1.2,
    ),
    "pizza": SectionVocab(
        "Pizza",
        (
            "Margherita",
            "Pepperoni",
            "Four Cheese",
            "Hawaiian",
            "Meat Lovers",
            "Veggie Supreme",
            "BBQ Chicken",
        ),
        (),
        ("mozzarella", "tomato sauce", "pepperoni", "pineapple", "mushrooms", "peppers", "sausage"),
        1.3,
        (('10"', '12"', '16"'), ("Small", "Medium", "Large"), ("S", "M", "L")),
    ),
    "burgers": SectionVocab(
        "Burgers",
        (
            "Cheeseburger",
            "Classic Burger",
            "Bacon Burger",
            "Chicken Sandwich",
            "Double Smash",
            "Veggie Burger",
        ),
        ("Deluxe", "Spicy", "BBQ", "Mushroom Swiss"),
        ("beef patty", "cheddar", "bacon", "pickles", "lettuce", "tomato", "brioche bun"),
        1.0,
    ),
    "snacks": SectionVocab(
        "Sides & Snacks",
        ("French Fries", "Onion Rings", "Mozzarella Sticks", "Chicken Wings", "Sweet Potato Fries", "Nachos"),
        ("Large", "Loaded", "Spicy"),
        ("ranch", "ketchup", "buffalo sauce", "cheese sauce"),
        0.5,
    ),
    "sides": SectionVocab(
        "Sides",
        ("Mashed Potatoes", "Coleslaw", "Rice Pilaf", "Steamed Broccoli", "Corn on the Cob", "Side Salad"),
        (),
        (),
        0.4,
    ),
    "desserts": SectionVocab(
        "Desserts",
        (
            "Cheesecake",
            "Tiramisu",
            "Apple Pie",
            "Chocolate Brownie",
            "Ice Cream",
            "Key Lime Pie",
            "Creme Brulee",
        ),
        ("New York", "a la Mode", "Classic", "Salted Caramel"),
        ("cream cheese", "mascarpone", "berries", "chocolate", "caramel", "vanilla"),
        0.7,
    ),
    "drinks": SectionVocab(
        "Drinks",
        ("Lemonade", "Iced Tea", "Orange Juice", "Soda", "Sparkling Water", "Milkshake", "Hot Tea"),
        ("Fresh", "Sweet", "Unsweetened", "Strawberry"),
        (),
        0.35,
    ),
    "coffee": SectionVocab(
        "Coffee",
        ("Espresso", "Americano", "Cappuccino", "Latte", "Flat White", "Mocha", "Cold Brew", "Hot Chocolate"),
        ("Vanilla", "Oat Milk", "Caramel", "Iced"),
        (),
        1.0,
        (("8 oz", "12 oz", "16 oz"), ("Small", "Medium", "Large"), ("S", "M", "L")),
    ),
    "bakery": SectionVocab(
        "Bakery",
        ("Croissant", "Cinnamon Roll", "Blueberry Muffin", "Scone", "Bagel", "Danish", "Banana Bread"),
        ("Almond", "Chocolate", "with Cream Cheese", "Butter"),
        (),
        0.8,
    ),
}

RU_VENUES: dict[str, VenueVocab] = {
    "cafe": VenueVocab(
        ("Кафе «Уют»", "Кафе «Ромашка»", "Кофейня-бистро «Окно»", "Кафе «Веранда»", "Бистро «Сезоны»"),
        ("breakfast", "salads", "soups", "mains", "desserts", "drinks"),
        (250, 750),
        ("Время приготовления 15–20 минут", "Вес указан для готового блюда", "Тел. +7 (495) 123-45-67"),
    ),
    "burger": VenueVocab(
        ("Burger Lab", "Бургерная «Гриль»", "Smash House", "Бургерная №5"),
        ("burgers", "snacks", "desserts", "drinks"),
        (250, 650),
        ("Доставка: 8 800 555-35-35", "ул. Ленина, 12", "Работаем с 10:00 до 23:00"),
    ),
    "pizzeria": VenueVocab(
        ("Пиццерия «Неаполь»", "Pizza Point", "Пиццерия «Дровяная печь»"),
        ("pizza", "pasta", "salads", "drinks"),
        (400, 950),
        ("Тесто готовим каждый день", "Заказ по телефону 8 (812) 700-10-20", "Пицца 30 см — 8 кусочков"),
    ),
    "coffee": VenueVocab(
        ("Кофейня «Зерно»", "Coffee Point", "Кофейня «Утро»", "Brew & Bake"),
        ("coffee", "drinks", "bakery", "desserts"),
        (150, 400),
        ("Альтернативное молоко +60 ₽", "Сироп +40 ₽", "Wi-Fi: coffee2024"),
    ),
    "canteen": VenueVocab(
        ("Столовая №1", "Столовая «Домашняя кухня»", "Обеды «Как дома»"),
        ("soups", "mains", "sides", "salads", "drinks"),
        (60, 260),
        ("Комплексный обед с 12:00 до 15:00", "Порция 250 г", "пр. Мира, 45, 2 этаж"),
    ),
}

EN_VENUES: dict[str, VenueVocab] = {
    "cafe": VenueVocab(
        ("The Corner Cafe", "Sunny Side Diner", "Maple Street Cafe", "Bluebird Bistro"),
        ("breakfast", "salads", "soups", "mains", "desserts", "drinks"),
        (7, 19),
        ("Served daily 7am - 3pm", "Please inform us of any allergies", "Call (555) 214-7788"),
    ),
    "burger": VenueVocab(
        ("Patty Shack", "Smash Bros Burgers", "The Burger Joint", "Grill Masters"),
        ("burgers", "snacks", "desserts", "drinks"),
        (6, 15),
        ("Add cheese +$1.50", "Order online at burgerjoint.example", "Open 11am - 10pm"),
    ),
    "pizzeria": VenueVocab(
        ("Tony's Pizzeria", "Slice of Brooklyn", "Wood Fire Pizza Co."),
        ("pizza", "pasta", "salads", "drinks"),
        (11, 24),
        ("Extra toppings $2 each", "Delivery (555) 320-1100", "Gluten-free crust available"),
    ),
    "coffee": VenueVocab(
        ("Daily Grind", "Bean There", "The Roastery", "Morning Brew"),
        ("coffee", "drinks", "bakery", "desserts"),
        (3, 6.5),
        ("Oat or almond milk +$0.75", "Extra shot +$1", "123 Main St"),
    ),
    "canteen": VenueVocab(
        ("Campus Dining Hall", "The Lunch Counter", "Workday Canteen"),
        ("soups", "mains", "sides", "salads", "drinks"),
        (3, 11),
        ("Lunch served 11:30 - 2:00", "Meal deal: entree + side + drink", "Building C, 1st floor"),
    ),
}

VOCAB = {
    "ru": (RU_SECTIONS, RU_VENUES),
    "en": (EN_SECTIONS, EN_VENUES),
}
