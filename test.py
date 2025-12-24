import argparse
import time
import torch

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--num', type=int, required=True)
    args = parser.parse_args()
    num = args.num
    
    tensor = torch.zeros((600, 600), device='cuda')
    for _ in range(20):
        num += 1
        print(num)
        print(tensor.shape)
        time.sleep(1)
        
