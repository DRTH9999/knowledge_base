import os
from dotenv import load_dotenv
load_dotenv()


class MineruConfig:
    mineru_token = os.getenv('MINERU_TOKEN')
    mineru_base_url = os.getenv('MINERU_BASE_URL')