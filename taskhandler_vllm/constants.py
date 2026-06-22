# Define the Prompt Template inline for PaliGemma (no <image> placeholder needed)
PROMPT_TEMPLATE = (
    "Extract structured metadata from this image. Output a JSON object with keys 'caption', 'tags' (list of strings), and 'primary_color'.\n"
)
