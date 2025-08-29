# FILE: ./utils/json_utils.py

import pandas as pd
import numpy as np
from datetime import datetime, date

def custom_json_serializer(obj):
    """
    A custom JSON serializer to handle special data types from
    DolphinDB, Pandas, and Numpy.
    """
    # 1. 处理DolphinDB的Timestamp和相关时间类型
    #    DolphinDB的Timestamp对象通常可以被Pandas识别为pd.Timestamp
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        # 将所有时间相关的对象统一转换为ISO 8601格式的字符串
        # 这是Web API中最标准的时间表示方式
        return obj.isoformat()

    # 2. 处理Numpy的特殊数值类型 (在Pandas中很常见)
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        # 将Numpy的数字类型转换为Python原生的int/float/bool
        return obj.item()

    # 3. 处理Numpy的数组 (如果需要的话)
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # 如果遇到其他不认识的类型，抛出原始错误
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")