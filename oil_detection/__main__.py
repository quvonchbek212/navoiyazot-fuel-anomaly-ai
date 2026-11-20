import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description='ATIL Yoqilg‘i AI tahlili')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8031, type=int)
    args = parser.parse_args()
    uvicorn.run('oil_detection.app:app', host=args.host, port=args.port)


if __name__ == '__main__':
    main()
