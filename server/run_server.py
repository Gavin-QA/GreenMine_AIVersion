import uvicorn
import logging

if __name__ == "__main__":
    logging.info("🚀 启动 Electron AI Vision Testing Platform 服务...")
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=False)
