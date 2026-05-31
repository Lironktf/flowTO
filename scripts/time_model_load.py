"""Time how long it takes to load the xgboost demand model. Nothing else."""
import os, time

PKL = "models/demand_model.pkl"
print(f"file: {PKL}  ({os.path.getsize(PKL)/1e6:.1f} MB)", flush=True)

t0 = time.perf_counter()
import joblib
t1 = time.perf_counter()
print(f"import joblib:        {t1-t0:6.2f} s", flush=True)

m = joblib.load(PKL)
t2 = time.perf_counter()
print(f"joblib.load(pkl):     {t2-t1:6.2f} s", flush=True)
print(f"--> TOTAL cold load:  {t2-t0:6.2f} s", flush=True)
print(f"model kind: {m.get('kind')}  metrics: {m.get('metrics')}", flush=True)

# second load (warm OS file cache) to separate disk vs deserialize cost
t3 = time.perf_counter()
joblib.load(PKL)
print(f"second load (warm):   {time.perf_counter()-t3:6.2f} s", flush=True)
