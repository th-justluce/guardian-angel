import os
import json
import re
from transformers import pipeline

CACHE_FOLDER = 'cache'
OPEN_AI_WHISPER = "openai/whisper-small"

os.makedirs(CACHE_FOLDER, exist_ok=True)

# Global settings for timestamp adjustment.
TIME_OFFSET = 1740494847
ADJUST_TIME = True    # Set to False if you want to leave timestamps unmodified.
ADD_OFFSET = True     # Set to False to subtract the relative time from TIME_OFFSET.

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
# Timestamp adjustment helper function
# ---------------------------
def adjust_timecodes(transcription, offset=1740542404, add=True):
    """
    Adjusts all time codes in the transcription. For each timestamp (a tuple of (start, end)):
      - If add is True: new time = (start + offset, end + offset)
      - If add is False: new time = (offset - end, offset - start)
    This function updates timestamps for both individual 'chunks' and the grouped 'punctuation_chunks'.
    """
    def adjust(ts):
        start, end = ts
        if add:
            return (start + offset, end + offset)
        else:
            # Swap start and end when subtracting so that start < end.
            return (offset - end, offset - start)
    
    if 'chunks' in transcription:
        for chunk in transcription['chunks']:
            if 'timestamp' in chunk:
                chunk['timestamp'] = adjust(chunk['timestamp'])
    if 'punctuation_chunks' in transcription:
        for segment in transcription['punctuation_chunks']:
            if 'timestamp' in segment:
                segment['timestamp'] = adjust(segment['timestamp'])
    return transcription

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

# Apply timestamp adjustments if desired.
if ADJUST_TIME:
    processed_transcription = adjust_timecodes(processed_transcription, offset=TIME_OFFSET, add=ADD_OFFSET)

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
        parsed_json = json.load(f)
else:
    from llama_cpp import Llama

    llm = Llama(
        model_path="Meta-Llama-3-8B-Instruct.Q2_K.gguf",
        n_gpu_layers=-1,
        num_gpu=-1,
        verbose=True,
        seed=1337,
        n_ctx=4096
    )

    output = llm(
        formatted_prompt,
        max_tokens=None, # Generate up to 32 tokens, set to None to generate up to the end of the context window
        stop=["Q:", "]"], # Stop generating just before the model would generate a new question
        echo=True # Echo the prompt back in the output
    ) # Generate a completion, can also call create_completion
    
    raw_text = output['choices'][0]['text']

    # Step 1: Remove the echoed prompt.
    # Find the start of the answer marker ("A:") and take the substring from there.
    answer_start = raw_text.find("A:")
    if answer_start != -1:
        answer_text = raw_text[answer_start:]
    else:
        answer_text = raw_text

    # Step 2: Extract the JSON block.
    # We assume the JSON is between triple backticks.
    parts = answer_text.split("```")
    if len(parts) >= 3:
        json_text = parts[1].strip()  # The JSON block is in the first code block.
    else:
        json_text = answer_text.strip()

    # Step 3: Fix the missing closing bracket.
    if not json_text.rstrip().endswith("]"):
        json_text += "\n]"

    print("Fixed JSON text:")
    print(json_text)

    # Step 4: Parse the JSON to verify it works.
    try:
        parsed_json = json.loads(json_text)
        print("\nParsed JSON:")
        print(parsed_json)
    except json.JSONDecodeError as e:
        print("Error parsing JSON:", e)

    # Cache the response.
    with open(openai_cache_file, "w") as f:
        json.dump(parsed_json, f)
    print(f"OpenAI response cached to {openai_cache_file}")

print("LLM response:")
print(json.dumps(parsed_json, indent=2))
