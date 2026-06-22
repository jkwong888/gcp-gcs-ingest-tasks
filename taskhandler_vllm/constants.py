from pydantic import BaseModel, Field
from typing import List

class ImageMetadataAnalysis(BaseModel):
    """
    Pydantic model representing the structured JSON output schema
    enforced on the Vision-Language Model.
    """
    caption: str = Field(description="A short, descriptive caption of the image.")
    tags: List[str] = Field(description="A list of relevant tags or labels for the objects/concepts in the image.")
    primary_color: str = Field(description="The dominant or primary color observed in the image.")

# Define the Prompt Template inline
PROMPT_TEMPLATE = (
    "USER: <image>\n"
    "Extract structured metadata from this image. Output a JSON object with keys 'caption', 'tags' (list of strings), and 'primary_color'.\n"
    "ASSISTANT:"
)
