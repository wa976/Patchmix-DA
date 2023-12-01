import matplotlib.pyplot as plt
import torchaudio
from matplotlib.axes import Axes


from curses import meta
import os
import cv2
import pickle
import random
import numpy as np
import pandas as pd
from tqdm import tqdm

#import librosa
import torch
from torch.utils.data import Dataset
from copy import deepcopy
from PIL import Image

from .icbhi_util import get_annotations, save_image, generate_fbank, get_individual_cycles_librosa, split_pad_sample, generate_mel_spectrogram, concat_augmentation
from .icbhi_util import get_individual_cycles_torchaudio,get_individual_cycles_torchaudio_iphone, cut_pad_sample_torchaudio
from .augmentation import augment_raw_audio


class ICBHIDataset_train(Dataset):
    def __init__(self, train_flag, transform, args, print_flag=True, mean_std=False,save_image=0):
        
        
        data_folder = os.path.join(args.data_folder, 'hospital_dataset/audio_data')
        folds_file = os.path.join(args.data_folder, 'hospital_foldwise.txt')
        # data_folder = os.path.join(args.data_folder, 'stethoscope_dataset')
        # folds_file = os.path.join(args.data_folder, 'iphone_foldwise.txt')
        
        test_fold = args.test_fold
        
        self.data_folder = data_folder
        self.train_flag = train_flag
        self.split = 'train' if train_flag else 'test'
        self.transform = transform
        self.args = args
        self.mean_std = mean_std

        # parameters for spectrograms
        self.sample_rate = args.sample_rate
        self.desired_length = args.desired_length
        self.pad_types = args.pad_types
        self.nfft = args.nfft
        self.hop = self.nfft // 2
        self.n_mels = args.n_mels
        self.f_min = 50
        self.f_max = 2000
        self.dump_images = False



    
    
        # ==========================================================================
        filenames = os.listdir(data_folder)
        filenames =set([f.strip().split('.')[0] for f in filenames if '.wav' in f])
       
        # ==========================================================================

        # ==========================================================================
        """ train-test split based on train_flag and test_fold """
        if test_fold in ['0', '1', '2', '3', '4']:  # from RespireNet, 80-20% split
            patient_dict = {}
            all_patients = open(folds_file).read().splitlines()
            for line in all_patients:
                idx, fold = line.strip().split(' ')
                if train_flag and int(fold) != int(test_fold):
                    patient_dict[idx] = fold
                elif train_flag == False and int(fold) == int(test_fold):
                    patient_dict[idx] = fold
            
            if print_flag:
                print('*' * 20)
                print('Train and test 80-20% split with test_fold {}'.format(test_fold))
                print('Patience number in {} dataset: {}'.format(self.split, len(patient_dict)))

        # ==========================================================================

        self.filenames = []
        for f in filenames:
            idx = f.split('-')[0] if test_fold in ['0', '1', '2', '3', '4'] else f
            #print(f,idx)
            if idx in patient_dict:
                self.filenames.append(f)

        
        self.audio_data = []  # each sample is a tuple with (audio_data, label, filename)
        self.labels = []

        if print_flag:
            print('*' * 20)  
            print("Extracting individual breathing cycles..")

        self.cycle_list = []
        self.filename_to_label = {}
        self.classwise_cycle_list = [[] for _ in range(args.n_cls)]

        # ==========================================================================
        """ extract individual cycles by librosa or torchaudio """
        for idx, filename in enumerate(self.filenames):
            self.filename_to_label[filename] = []
            
            last_letter = filename[-1]
            #print(last_letter)
            temp_class = 0
            
            if last_letter == 'C':
                temp_class = 1
            elif last_letter == 'W':
                temp_class = 1
            elif last_letter == 'B':
                temp_class = 1
            elif last_letter == 'N':
                temp_class = 0
            
           
            
            sample_data = get_individual_cycles_torchaudio_iphone(args, data_folder, filename, args.sample_rate, args.n_cls)


            
          
   

            cycles_with_labels = [(data[0], data[1]) for data in sample_data]
            
     
            
            self.cycle_list.extend(cycles_with_labels)
            
 
            
            for d in cycles_with_labels:

                self.filename_to_label[filename].append(d[1])
                self.classwise_cycle_list[d[1]].append(d)
            
            
            
        for sample in self.cycle_list:
            # "SCL" version
            self.audio_data.append(sample)
        # ==========================================================================

        self.class_nums = np.zeros(args.n_cls)
        for sample in self.audio_data:
            self.class_nums[sample[1]] += 1
            self.labels.append(sample[1])
        self.class_ratio = self.class_nums / sum(self.class_nums) * 100
        
        if print_flag:
            print('[Preprocessed {} dataset information]'.format(self.split))
            print('total number of audio data: {}'.format(len(self.audio_data)))
            for i, (n, p) in enumerate(zip(self.class_nums, self.class_ratio)):
                print('Class {} {:<9}: {:<4} ({:.1f}%)'.format(i, '('+args.cls_list[i]+')', int(n), p))    
        
        # ==========================================================================
        """ convert mel-spectrogram """
        self.audio_images = []
        for index in range(len(self.audio_data)):
            audio, label = self.audio_data[index][0], self.audio_data[index][1]
            
            #print("label : ", label)

            
            audio_image = []
            # self.aug_times = 1 + 5 * self.args.augment_times  # original + five naa augmentations * augment_times (optional)
            for aug_idx in range(self.args.raw_augment+1): 
                if aug_idx > 0:
                    if self.train_flag and not mean_std:
                        if label ==1 :
                            audio = augment_raw_audio(audio.numpy(), self.sample_rate, self.args)
                            
                            # "RespireNet" version: pad incase smaller than desired length
                            # audio = split_pad_sample([audio, 0,0], self.desired_length, self.sample_rate, types=self.pad_types)[0][0]
                            # Debug print to check what 'audio' contains
                            #print(f"Audio before cut_pad_sample_torchaudio: {audio}")
                            # "SCL" version: cut longer sample or pad sample
                            audio = cut_pad_sample_torchaudio(torch.tensor(audio), args)
                    else:
                        audio_image.append(None)
                        continue
                    

                image = generate_fbank(audio, self.sample_rate, n_mels=self.n_mels)
                # image = generate_mel_spectrogram(audio.squeeze(0).numpy(), self.sample_rate, n_mels=self.n_mels, f_max=self.f_max, nfft=self.nfft, hop=self.hop, args=self.args) # image [n_mels, 251, 1]
                
                
                # blank region clipping from "RespireNet" paper..
                if self.args.blank_region_clip:     
                    image_copy = deepcopy(generate_fbank(audio, self.sample_rate, n_mels=self.n_mels))
                    # image_copy = deepcopy(generate_mel_spectrogram(audio.squeeze(0).numpy(), self.sample_rate, n_mels=self.n_mels, f_max=self.f_max, nfft=self.nfft, hop=self.hop, args=self.args)) # image [n_mels, 251, 1]                    

                    image_copy[image_copy < 10] = 0
                    for row in range(image_copy.shape[0]):
                        black_percent = len(np.where(image_copy[row,:] == 0)[0]) / len(image_copy[row,:])
                        # if there is row that is filled by more than 20% regions, stop and remember that `row`
                        if black_percent < 0.80:
                            break

                    # delete black percent
                    if row + 1 < image.shape[0]:
                        image = image[row+1:,:,:]
                        
                    
                    image = cv2.resize(image, (image.shape[1], self.n_mels), interpolation=cv2.INTER_LINEAR)
                    image = image[..., np.newaxis]

            
                       
                audio_image.append(image)
            self.audio_images.append((audio_image, label))
            
            if self.dump_images:
                save_image(audio_image, './')
                self.dump_images = False
             
            
        
        self.h, self.w, _ = self.audio_images[0][0][0].shape
        # ==========================================================================

    def __getitem__(self, index):
        audio_images, label = self.audio_images[index][0], self.audio_images[index][1]
        filename = self.filenames[index]
        
        
        if self.args.raw_augment and self.train_flag and not self.mean_std:
            aug_idx = random.randint(0, self.args.raw_augment)
            audio_image = audio_images[aug_idx]
        else:
            audio_image = audio_images[0]
            
        
        if self.transform is not None:
            audio_image = self.transform(audio_image)
        
        
        return audio_image, label, filename

    def __len__(self):
        return len(self.audio_data)
    
    
    
class ICBHIDataset_val(Dataset):
    def __init__(self, train_flag, transform, args, print_flag=True, mean_std=False,save_image=0):
        
        
        data_folder = os.path.join(args.data_folder, 'iphone_dataset')
        folds_file = os.path.join(args.data_folder, 'iphone_foldwise.txt')
        # data_folder = os.path.join(args.data_folder, 'stethoscope_dataset')
        # folds_file = os.path.join(args.data_folder, 'iphone_foldwise.txt')
        
        test_fold = args.test_fold
        
        self.data_folder = data_folder
        self.train_flag = train_flag
        self.split = 'train' if train_flag else 'test'
        self.transform = transform
        self.args = args
        self.mean_std = mean_std

        # parameters for spectrograms
        self.sample_rate = args.sample_rate
        self.desired_length = args.desired_length
        self.pad_types = args.pad_types
        self.nfft = args.nfft
        self.hop = self.nfft // 2
        self.n_mels = args.n_mels
        self.f_min = 50
        self.f_max = 2000
        self.dump_images = False



    
    
        # ==========================================================================
        filenames = os.listdir(data_folder)
        filenames =set([f.strip().split('.')[0] for f in filenames if '.wav' in f])
       
        # ==========================================================================

        # ==========================================================================
        """ train-test split based on train_flag and test_fold """
        if test_fold in ['0', '1', '2', '3', '4']:  # from RespireNet, 80-20% split
            patient_dict = {}
            all_patients = open(folds_file).read().splitlines()
            for line in all_patients:
                idx, fold = line.strip().split(' ')
                if train_flag and int(fold) != int(test_fold):
                    patient_dict[idx] = fold
                elif train_flag == False and int(fold) == int(test_fold):
                    patient_dict[idx] = fold
            
            if print_flag:
                print('*' * 20)
                print('Train and test 80-20% split with test_fold {}'.format(test_fold))
                print('Patience number in {} dataset: {}'.format(self.split, len(patient_dict)))

        # ==========================================================================

        self.filenames = []
        for f in filenames:
            idx = f.split('-')[0] if test_fold in ['0', '1', '2', '3', '4'] else f
            #print(f,idx)
            if idx in patient_dict:
                self.filenames.append(f)

        
        self.audio_data = []  # each sample is a tuple with (audio_data, label, filename)
        self.labels = []

        if print_flag:
            print('*' * 20)  
            print("Extracting individual breathing cycles..")

        self.cycle_list = []
        self.filename_to_label = {}
        self.classwise_cycle_list = [[] for _ in range(args.n_cls)]

        # ==========================================================================
        """ extract individual cycles by librosa or torchaudio """
        for idx, filename in enumerate(self.filenames):
            self.filename_to_label[filename] = []
            
            last_letter = filename[-1]
            #print(last_letter)
            temp_class = 0
            
            if last_letter == 'C':
                temp_class = 1
            elif last_letter == 'W':
                temp_class = 1
            elif last_letter == 'B':
                temp_class = 1
            elif last_letter == 'N':
                temp_class = 0
            
           
            
            sample_data = get_individual_cycles_torchaudio_iphone(args, data_folder, filename, args.sample_rate, args.n_cls)


            
          
   

            cycles_with_labels = [(data[0], data[1]) for data in sample_data]
            
     
            
            self.cycle_list.extend(cycles_with_labels)
            
 
            
            for d in cycles_with_labels:

                self.filename_to_label[filename].append(d[1])
                self.classwise_cycle_list[d[1]].append(d)
            
            
            
        for sample in self.cycle_list:
            # "SCL" version
            self.audio_data.append(sample)
        # ==========================================================================

        self.class_nums = np.zeros(args.n_cls)
        for sample in self.audio_data:
            self.class_nums[sample[1]] += 1
            self.labels.append(sample[1])
        self.class_ratio = self.class_nums / sum(self.class_nums) * 100
        
        if print_flag:
            print('[Preprocessed {} dataset information]'.format(self.split))
            print('total number of audio data: {}'.format(len(self.audio_data)))
            for i, (n, p) in enumerate(zip(self.class_nums, self.class_ratio)):
                print('Class {} {:<9}: {:<4} ({:.1f}%)'.format(i, '('+args.cls_list[i]+')', int(n), p))    
        
        # ==========================================================================
        """ convert mel-spectrogram """
        self.audio_images = []
        for index in range(len(self.audio_data)):
            audio, label = self.audio_data[index][0], self.audio_data[index][1]
            
            #print("label : ", label)

            
            audio_image = []
            # self.aug_times = 1 + 5 * self.args.augment_times  # original + five naa augmentations * augment_times (optional)
            for aug_idx in range(self.args.raw_augment+1): 
                if aug_idx > 0:
                    if self.train_flag and not mean_std:
                        if label ==1 :
                            audio = augment_raw_audio(audio.numpy(), self.sample_rate, self.args)
                            
                            # "RespireNet" version: pad incase smaller than desired length
                            # audio = split_pad_sample([audio, 0,0], self.desired_length, self.sample_rate, types=self.pad_types)[0][0]
                            # Debug print to check what 'audio' contains
                            #print(f"Audio before cut_pad_sample_torchaudio: {audio}")
                            # "SCL" version: cut longer sample or pad sample
                            audio = cut_pad_sample_torchaudio(torch.tensor(audio), args)
                    else:
                        audio_image.append(None)
                        continue
                    

                image = generate_fbank(audio, self.sample_rate, n_mels=self.n_mels)
                # image = generate_mel_spectrogram(audio.squeeze(0).numpy(), self.sample_rate, n_mels=self.n_mels, f_max=self.f_max, nfft=self.nfft, hop=self.hop, args=self.args) # image [n_mels, 251, 1]
                
                
                # blank region clipping from "RespireNet" paper..
                if self.args.blank_region_clip:     
                    image_copy = deepcopy(generate_fbank(audio, self.sample_rate, n_mels=self.n_mels))
                    # image_copy = deepcopy(generate_mel_spectrogram(audio.squeeze(0).numpy(), self.sample_rate, n_mels=self.n_mels, f_max=self.f_max, nfft=self.nfft, hop=self.hop, args=self.args)) # image [n_mels, 251, 1]                    

                    image_copy[image_copy < 10] = 0
                    for row in range(image_copy.shape[0]):
                        black_percent = len(np.where(image_copy[row,:] == 0)[0]) / len(image_copy[row,:])
                        # if there is row that is filled by more than 20% regions, stop and remember that `row`
                        if black_percent < 0.80:
                            break

                    # delete black percent
                    if row + 1 < image.shape[0]:
                        image = image[row+1:,:,:]
                        
                    
                    image = cv2.resize(image, (image.shape[1], self.n_mels), interpolation=cv2.INTER_LINEAR)
                    image = image[..., np.newaxis]

            
                       
                audio_image.append(image)
            self.audio_images.append((audio_image, label))
            
            if self.dump_images:
                save_image(audio_image, './')
                self.dump_images = False
             
            
        
        self.h, self.w, _ = self.audio_images[0][0][0].shape
        # ==========================================================================

    def __getitem__(self, index):
        audio_images, label = self.audio_images[index][0], self.audio_images[index][1]
        filename = self.filenames[index]
        
        
        if self.args.raw_augment and self.train_flag and not self.mean_std:
            aug_idx = random.randint(0, self.args.raw_augment)
            audio_image = audio_images[aug_idx]
        else:
            audio_image = audio_images[0]
            
        
        if self.transform is not None:
            audio_image = self.transform(audio_image)
        
        
        return audio_image, label, filename

    def __len__(self):
        return len(self.audio_data)