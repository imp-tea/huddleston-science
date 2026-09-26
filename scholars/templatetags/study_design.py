from django import template

register = template.Library()
PALETTE = {
    "Arts and Music": ("#806128", "#eee5cb", "music"),
    "Everyday Life and Culture": ("#805b39", "#eee3d3", "spark"),
    "Geography": ("#49634c", "#e1e6d6", "globe"),
    "Literature": ("#77566a", "#ece0e4", "book"),
    "Mathematics": ("#69603a", "#e9e4ce", "orbit"),
    "Popular Media and Entertainment": ("#805d47", "#eee0d5", "spark"),
    "Religion and Mythology": ("#6b5b77", "#e8e1ed", "spark"),
    "Science and Technology": ("#476779", "#dfe7e9", "orbit"),
    "Social Science and Philosophy": ("#64683f", "#e5e6d3", "orbit"),
    "Sports and Games": ("#516d48", "#e1e7d7", "spark"),
    "U.S. History": ("#82573c", "#efe0d2", "column"),
    "World History": ("#765e33", "#ece3cb", "column"),
}


@register.filter
def category_style(category):
    accent, wash, _ = PALETTE.get(str(category), PALETTE["Geography"])
    return f"--accent:{accent};--wash:{wash}"


@register.filter
def category_icon(category):
    return PALETTE.get(str(category), PALETTE["Geography"])[2]
