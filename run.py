"""启动Streamlit应用程序的脚本"""

import anyio
from computer_use_demo.streamlit import main

if __name__ == "__main__":
    anyio.run(main, backend="asyncio")
