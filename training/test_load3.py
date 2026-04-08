"""Minimal model load test with progress tracking"""
import os, sys, gc, signal, faulthandler

# Enable faulthandler to get traceback even on segfaults
faulthandler.enable()

print("Step 1: Importing torch...", flush=True)
import torch

print("Step 2: Importing transformers...", flush=True)
from transformers import AutoModelForCausalLM, AutoConfig, BitsAndBytesConfig

print("Step 3: Creating quantization config...", flush=True)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

print("Step 4: Loading config only...", flush=True)
config = AutoConfig.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
print(f"  Model config loaded: {config.model_type}, hidden={config.hidden_size}", flush=True)

print("Step 5: Calling from_pretrained (this is where it crashes)...", flush=True)
sys.stdout.flush()
sys.stderr.flush()

try:
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    print(f"Step 6: Model loaded successfully! GPU mem: {torch.cuda.memory_allocated()/1024**3:.1f} GB", flush=True)
    del model
except Exception as e:
    print(f"EXCEPTION at step 5: {e}", flush=True)
    import traceback
    traceback.print_exc()

gc.collect()
torch.cuda.empty_cache()
print("DONE", flush=True)
