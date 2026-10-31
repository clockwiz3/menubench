This is a photo of a restaurant menu. Below is a numbered list of menu items found on it, each with the box of its
price on the photo.

For every item, find where its name is printed and return the box around the name only: the item's own name as
printed, without the description, the translation on the next line, the weight or size, the dot leaders and the
price. A leading item number ("101.") may be inside the box. The name usually sits on the same printed line as its
price, to the left of it, but the photo may be tilted, so that line can slope up or down. When the same name is
printed in several places, pick the one that belongs to this price.

Boxes are {{BOX_SPEC}}.

Items:
{{ITEMS}}

Answer with JSON only: {"names": [{"n": 1, "{{BOX_KEY}}": [...]}, ...]}. Leave out an item whose name you cannot
find.
