import base64
from typing import Optional

from openai import OpenAI

from config import get_openai_settings

settings = get_openai_settings()

PROMPTS = {
    "Translate": """Task: Translate the user-provided content according to the following rules.

1. Language direction
   - If the input is in Chinese, translate it into English.
   - If the input is in any other language, translate it into Chinese.

2. Dictionary-style expansion
   - If the input is a single word or a short phrase, in addition to the translation, 提供类似牛津词典格式的词条:
     - Provide a clear definition in the target language.
     - Provide several example usages in the target language.

3. Output constraints
   - Output only the following sections:
     - Source Language
     - Target Language
     - Mode (Translation or Dictionary)
     - Translation
     - Definition (only for words or short phrases, in target language)
   - Do not include explanations, meta comments, or any content in the source language.
Return your answer in JSON format like this:
{
  "Source Language": "Chinese",
  "Target Language": "English",
  "Mode": "Translation",
  "Translation": "Hello, world!"
}
{
  "Source Language": "English",
  "Target Language": "Chinese",
  "Mode": "Dictionary",
  "Translation": "担心，担忧",
  "Definition": "Worry:\n1(n.): A feeling of anxiety or concern about a situation or event.\n2(v.): To feel anxious or concerned about something.\n"
}
""",
    "Summarize": "Summarize the content concisely. Only return the summary.",
    "Format": "Format the content to markdown format. Only return the formatted text. (Do not use ``` for markdown blocks.)",
    "Improve": "Improve grammar, vocabulary, and style. Only return the improved text.",
    "Explain": "Explain the content simply and clearly. Only return the explanation.",
    "OCR": "Perform Optical Character Recognition (OCR) on the provided image and extract the text. Only return the extracted text. If the image contains equations, convert them into LaTeX format ($ ... $).",
}


def _build_image_content(image: bytes) -> dict:
    b64 = base64.b64encode(image).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{b64}",
        },
    }


def llm_chat(
    text: str,
    image: Optional[bytes] = None,
    model_size: str = "medium",
    timeout: float = 120.0,
) -> str:
    """
    Call the configured LLM with optional image context.
    """
    model = settings["models"].get(model_size, settings["models"]["medium"])
    client = OpenAI(
        base_url=settings.get("base_url"),
        api_key=settings.get("api_key"),
        timeout=settings.get("timeout", timeout),
    )
    print(settings.get("base_url"), settings.get("api_key"))

    user_content: list[dict] = [{"type": "text", "text": text}]
    if image:
        user_content.append(_build_image_content(image))

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a helpful assistant."}],
        },
        {"role": "user", "content": user_content},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2000,
        temperature=0.6,
        timeout=timeout,
    )
    print(resp)
    return resp.choices[0].message.content or ""


def run_task(
    image: Optional[bytes], text: str, task: str, timeout: float = 120.0
) -> str:
    """
    Run a specific LLM task (OCR, Translate, Summarize, etc.) with the given text and optional image.
    """
    print("run_task:", task)
    task_key = task.lower()
    if task_key == "ocr" and image:
        prompt = PROMPTS.get("OCR", None)
        return llm_chat(prompt, image=image, model_size="medium", timeout=timeout)
    elif task_key == "translate":
        prompt = PROMPTS.get("Translate", None)
        full_prompt = f"{prompt}\n\nContent:\n{text}"
        resp = llm_chat(full_prompt, model_size="medium", timeout=timeout).strip()

        # strip out code blocks if any

        if resp.startswith("```") and resp.endswith("```"):
            resp = "\n".join(resp.split("\n")[1:-1])

        import json

        ret = ""
        try:
            data = json.loads(resp)
            for key in ["Translation", "Definition"]:
                if key in data:
                    ret += data[key] + "\n"
            ret = ret.strip()
        except Exception:
            ret = resp.strip()
        return ret
    elif task_key in ["summarize", "summary", "format", "improve", "explain"]:
        prompt = PROMPTS.get(task.capitalize(), None)
        full_prompt = f"{prompt}\n\nContent:\n{text}"
        return llm_chat(full_prompt, model_size="medium", timeout=timeout)
    return ""
