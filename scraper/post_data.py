from dataclasses import dataclass


@dataclass
class PostData:
    post_id: str
    author_name: str
    content: str
    post_url: str
    group_name: str
    matched_keyword: str
