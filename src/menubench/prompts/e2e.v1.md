You read restaurant menus. List every price printed in the image together with the menu item it belongs to.

For each price return:
- `price_text`: the price exactly as printed, with its currency sign if there is one (for example "350 ₽", "$12.50", "от 300").
- `item`: the name of the dish or drink this price is for, exactly as printed, without the size.
- `size`: the size label when the item is sold in several sizes and this price is for one of them (for example "M", "350 мл", "12\""), otherwise null.
- `{{BOX_KEY}}`: the tight box around the price text: {{BOX_SPEC}}.
- `confidence`: a number from 0 to 1, how sure you are that both the price and the item are right.

Do not list: crossed-out old prices, weights and volumes that are not prices, phone numbers, times, addresses, add-on surcharges in footnotes.

Answer with JSON only, no commentary:
{"prices": [{"price_text": "...", "item": "...", "size": null, "{{BOX_KEY}}": [...], "confidence": 0.9}]}
