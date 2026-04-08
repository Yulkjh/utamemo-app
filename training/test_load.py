import torch
import traceback
from transformers import AutoModelForCausalLM, BitsAndBytesConfig

print("Starting model load test...")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"Free GPU mem: {torch.cuda.mem_get_info()[0]/1024**3:.1f} GB")

try:
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    print("Loading model with 4bit quantization...")
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    print("Model loaded successfully!")
    print(f"GPU memory used: {torch.cuda.memory_allocated()/1024**3:.1f} GB")
    del model
    torch.cuda.empty_cache()
    print("Cleanup done.")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
