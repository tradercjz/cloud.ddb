def run_non_iter(x):
    return 123   # 普通对象，不可迭代

def run_iterable(x):
    return [1, 2, 3]  # 可迭代对象（list）

def run_generator(x):
    yield 1
    yield 2
    return 99   # 生成器有 return 值


def outer(run_func, name):
    print(f"\n=== 测试 {name} ===")
    try:
        z = yield from run_func(1)
        print(f"最终 z = {z!r}")
    except Exception as e:
        print(f"出错: {e!r}")


# 用来执行 outer 生成器
def test(run_func, name):
    gen = outer(run_func, name)
    for val in gen:
        print(f"yield 得到: {val!r}")


if __name__ == "__main__":
    test(run_non_iter, "非迭代对象")
    test(run_iterable, "可迭代对象")
    test(run_generator, "生成器")
