import cudf

raw = cudf.read_csv("v3.csv", header=None, nrows=50)
print(raw.to_pandas().to_string())