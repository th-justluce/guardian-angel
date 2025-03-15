import os
import json
import re
from dotenv import load_dotenv
from litellm import completion
from transformers import pipeline


CACHE_FOLDER = 'cache'
OPEN_AI_WHISPER = "openai/whisper-large-v3"

load_dotenv()
os.makedirs(CACHE_FOLDER, exist_ok=True)

# ---------------------------
# Caching functions for transcription
# ---------------------------
def load_cached_transcription(audio_file):
    """
    Loads a cached transcription from a JSON file if it exists.
    """
    cache_file = os.path.splitext(audio_file)[0] + "_transcription.json"
    cache_file = os.path.join(CACHE_FOLDER, cache_file)
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            print(f"Loading cached transcription from {cache_file}")
            return json.load(f)
    return None

def save_cached_transcription(audio_file, transcription):
    """
    Saves the transcription output to a JSON file for caching.
    """
    cache_file = os.path.splitext(audio_file)[0] + "_transcription.json"
    cache_file = os.path.join(CACHE_FOLDER, cache_file)
    with open(cache_file, 'w') as f:
        json.dump(transcription, f)
    print(f"Transcription cached to {cache_file}")

# ---------------------------
# Deduplication functions
# ---------------------------
def remove_repeats(text, window=5):
    """
    Removes consecutive repeated sequences of up to `window` words.
    """
    pattern = re.compile(
        r'\b((?:\S+\s+){1,' + str(window - 1) + r'}\S+)(\s+\1)+',
        flags=re.IGNORECASE
    )
    
    prev_text = None
    while prev_text != text:
        prev_text = text
        text = pattern.sub(r'\1', text)
    return text

def remove_repeated_chunks(chunks):
    """
    Removes consecutive duplicate word-level chunks based on their 'text' field.
    """
    if not chunks:
        return chunks
    
    cleaned_chunks = [chunks[0]]
    prev_text = chunks[0].get('text', '').strip().lower()
    for chunk in chunks[1:]:
        current_text = chunk.get('text', '').strip().lower()
        if current_text == prev_text:
            continue
        cleaned_chunks.append(chunk)
        prev_text = current_text
    return cleaned_chunks

# ---------------------------
# Punctuation-based grouping
# ---------------------------
def group_chunks_by_punctuation(cleaned_chunks):
    """
    Groups word-level cleaned chunks into segments based on sentence-ending punctuation.
    """
    segments = []
    current_segment = []
    for chunk in cleaned_chunks:
        current_segment.append(chunk)
        text_str = chunk.get('text', '').strip()
        if text_str and text_str[-1] in '.?!':
            segments.append(current_segment)
            current_segment = []
    if current_segment:
        segments.append(current_segment)
    
    grouped = []
    for seg in segments:
        combined_text = " ".join(ch['text'].strip() for ch in seg)
        start_time = seg[0]['timestamp'][0]
        end_time = seg[-1]['timestamp'][1]
        grouped.append({'text': combined_text, 'timestamp': (start_time, end_time)})
    return grouped

# ---------------------------
# Post-processing
# ---------------------------
def post_process_transcription(transcription, audio_file=None):
    """
    Processes a transcription output by:
      - Removing repeated phrases from the full transcript.
      - Deduplicating word-level chunks.
      - Grouping the cleaned word-level chunks into sentence segments based on punctuation.
    """
    raw_text = transcription.get('text', '')
    cleaned_text = remove_repeats(raw_text)
    transcription['cleaned_text'] = cleaned_text

    chunks = transcription.get('chunks', [])
    cleaned_chunks = remove_repeated_chunks(chunks)
    transcription['cleaned_chunks'] = cleaned_chunks

    punctuation_chunks = group_chunks_by_punctuation(cleaned_chunks)
    transcription['punctuation_chunks'] = punctuation_chunks

    return transcription

# ---------------------------
# Main transcription processing
# ---------------------------
audio_file = 'SWA2504.mp3'
# Try to load cached transcription.
raw_transcription = load_cached_transcription(audio_file)
if raw_transcription is None:
    print("Running transcription pipeline...")
    # FINE_TUNED_TEST = "Jzuluaga/wav2vec2-large-960h-lv60-self-en-atc-uwb-atcc-and-atcosim"
    pipe = pipeline("automatic-speech-recognition", model=OPEN_AI_WHISPER)
    raw_transcription = pipe(audio_file, return_timestamps='word')
    save_cached_transcription(audio_file, raw_transcription)
else:
    print("Using cached transcription.")

# Post-process the transcription.
processed_transcription = post_process_transcription(raw_transcription, audio_file=audio_file)
print("Processed transcription:")
print(json.dumps(processed_transcription, indent=2))

# ---------------------------
# New OpenAI Completion Call with Formatted Prompt
# ---------------------------
# 1) Read the compliant_state_prompt.txt template and replace the {RAW_TRANSCRIPT} placeholder
try:
    with open("compliant_state_prompt.txt", "r", encoding="utf-8") as f:
        prompt_template = f.read()
except FileNotFoundError:
    raise FileNotFoundError("The file 'compliant_state_prompt.txt' was not found.")

# Here we embed the punctuation chunks list into the template.
formatted_prompt = prompt_template.format(
    RAW_TRANSCRIPT=json.dumps(processed_transcription['punctuation_chunks'], indent=2)
)

# 2) Cache the OpenAI response.
openai_cache_file = os.path.splitext(audio_file)[0] + "_openai_response.json"

openai_cache_file = os.path.join(CACHE_FOLDER, openai_cache_file)
if os.path.exists(openai_cache_file):
    with open(openai_cache_file, "r") as f:
        print(f"Loading cached OpenAI response from {openai_cache_file}")
        openai_response = json.load(f)
else:
    print("Calling OpenAI completion with the formatted prompt...")
    openai_response_obj = completion(
      model="o3-mini",
      response_format={"type": "json_object"},
      messages=[
        {"role": "system", "content": "You are an expert ATC transcript analysis and expert in the field of aviation."},
        {"role": "user", "content": formatted_prompt}
      ]
    )
    # Extract and parse the OpenAI response.
    openai_response = json.loads(openai_response_obj.choices[0].message.content)
    
    # Cache the response.
    with open(openai_cache_file, "w") as f:
        json.dump(openai_response, f)
    print(f"OpenAI response cached to {openai_cache_file}")

print("OpenAI response:")
print(json.dumps(openai_response, indent=2))
