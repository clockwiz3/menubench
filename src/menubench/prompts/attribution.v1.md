This is a fragment of a restaurant menu. One price is marked with a red rectangle; OCR read it as "{{PRICE}}".

Which menu item is this price for?

Text lines that OCR found near this price (the answer is usually one of them, but OCR can be wrong):
{{LINES}}

Rules:
- `item` is the dish or drink name exactly as printed, without the size and without the description or ingredients. Section titles are not item names.
- If the item is sold in several sizes and the marked price is for one of them, put that size label into `size`.
- `status` is "current_price" for a normal price, "old_price" if the marked number is a crossed-out old price, "not_price" if it is not a price at all (a weight, volume, phone number, time, size label).
- `confidence` is a number from 0 to 1: how sure you are about `item`.

Answer with JSON only:
{"status": "current_price", "item": "...", "size": null, "confidence": 0.9}
