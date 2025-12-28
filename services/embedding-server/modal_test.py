import modal

app = modal.App('example-get-started')

@app.function()
def square(x: int) -> int:
    return x**2

@app.local_entrypoint()
def main():
    print(square.remote(2))