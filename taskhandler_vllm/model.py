from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

class TaskRequest(BaseModel):
    """
    Pydantic model representing the incoming task request payload.
    Supports GCS paths, base64 raw strings, or local file paths.
    """
    path: Optional[str] = Field(None, alias="gcsPath")
    b64input: Optional[str] = None
    job_id: str = Field(..., alias="jobId")

    model_config = ConfigDict(populate_by_name=True)

class ImageMetadataAnalysis(BaseModel):
    """
    Pydantic model representing the structured JSON output schema
    enforced on the Vision-Language Model.
    """
    caption: str = Field(description="A short, descriptive caption of the image.")
    tags: List[str] = Field(description="A list of relevant tags or labels for the objects/concepts in the image.")
    primary_color: str = Field(description="The dominant or primary color observed in the image.")
