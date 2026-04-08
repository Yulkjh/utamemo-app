import sys
import os
import gc
import traceback

# Force garbage collection before starting
gc.collect()

print(f"Python: {sys.version}", flush=True)
print(f"PID: {os.getpid()}", flush=True)

import torch
print(f"PyTorch: {torch.__version__}", flush=True)
print(f"CUDA: {torch.cuda.is_available()}", flush=True)
free_gpu, total_gpu = torch.cuda.mem_get_info()
print(f"GPU Memory: {free_gpu/1024**3:.1f} GB free / {total_gpu/1024**3:.1f} GB total", flush=True)

import psutil
ram = psutil.virtual_memory()
print(f"System RAM: {ram.available/1024**3:.1f} GB free / {ram.total/1024**3:.1f} GB total", flush=True)

try:
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    print("Imports OK", flush=True)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    print("BnB config created", flush=True)

    print("Calling from_pretrained...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    print(f"Model loaded! GPU mem: {torch.cuda.memory_allocated()/1024**3:.1f} GB", flush=True)
    del model
    gc.collect()
    torch.cuda.empty_cache()
    print("DONE", flush=True)

except Exception as e:
    print(f"EXCEPTION: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
