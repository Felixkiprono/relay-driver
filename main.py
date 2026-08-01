import uvicorn

from app.core import settings


def main() -> None:
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
