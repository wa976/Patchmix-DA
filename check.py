import os
import torch

print(torch.cuda.is_available())
print(len(os.listdir('./data/hospital_dataset/audio_data')))
print(torch.cuda.device_count())
device = torch.device('cuda:0')
print(torch.cuda.device_count())

