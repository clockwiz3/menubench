A restaurant menu lists the item "{{ITEM}}" at {{PRICE}}. We need to find the same item in the restaurant's till catalog. Till names are often abbreviated, transliterated, have typos, product codes or portion sizes.

Candidates from the catalog:
{{CANDIDATES}}

Order the candidates from most to least likely to be the same item. If none of them is the same dish or drink (a different dish, or only a similar one), say so. Do not guess: a wrong match puts a wrong price on a screen.

Answer with JSON only:
{"ranking": ["c001", "..."], "none_match": false, "reason": "one short sentence for the operator"}
