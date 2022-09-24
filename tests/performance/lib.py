ranking = {}

def print_perf(name, operation, t_start, t_end, iterations):
    t = t_end - t_start
    speed = round(iterations / t)
    print(f"{name} ({operation}) = {speed:,d} ops per second")

    if not operation in ranking:
        ranking[operation] = {}

    ranking[operation][name] = speed

def print_ranking():
    print('\nRanking:')
    for operation_name, operation in ranking.items():
        print(f'  {operation_name}:')
        top = None
        rank = 1
        for name, value in sorted(operation.items(), key=lambda i: i[1], reverse=True):
            if not top:
                top = value

            multiple = round(top/value, 2)
            print(f'    {rank} {name} = {value:,d} (factor {multiple})')
            rank += 1
