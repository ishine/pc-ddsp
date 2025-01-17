import os
import random
import numpy as np
import librosa
import torch
import random
from torch.utils.data import Dataset

def traverse_dir(
        root_dir,
        extension,
        amount=None,
        str_include=None,
        str_exclude=None,
        is_pure=False,
        is_sort=False,
        is_ext=True):

    file_list = []
    cnt = 0
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(extension):
                # path
                mix_path = os.path.join(root, file)
                pure_path = mix_path[len(root_dir)+1:] if is_pure else mix_path

                # amount
                if (amount is not None) and (cnt == amount):
                    if is_sort:
                        file_list.sort()
                    return file_list
                
                # check string
                if (str_include is not None) and (str_include not in pure_path):
                    continue
                if (str_exclude is not None) and (str_exclude in pure_path):
                    continue
                
                if not is_ext:
                    ext = pure_path.split('.')[-1]
                    pure_path = pure_path[:-(len(ext)+1)]
                file_list.append(pure_path)
                cnt += 1
    if is_sort:
        file_list.sort()
    return file_list


def get_data_loaders(args, whole_audio=False):
    data_train = AudioDataset(
        args.data.train_path,
        waveform_sec=args.data.duration,
        hop_size=args.data.block_size,
        sample_rate=args.data.sampling_rate,
        whole_audio=whole_audio,
        volume_aug=True)
    
    loader_train = torch.utils.data.DataLoader(
        data_train ,
        batch_size=args.train.batch_size if not whole_audio else 1,
        shuffle=True,
        num_workers=2,
        pin_memory=True
    )
    data_valid = AudioDataset(
        args.data.valid_path,
        waveform_sec=args.data.duration,
        hop_size=args.data.block_size,
        sample_rate=args.data.sampling_rate,
        whole_audio=True,
        volume_aug=False)
    loader_valid = torch.utils.data.DataLoader(
        data_valid,
        batch_size=1,
        shuffle=False,
        num_workers=1,
        pin_memory=True
    )
    return loader_train, loader_valid 


class AudioDataset(Dataset):
    def __init__(
        self,
        path_root,
        waveform_sec,
        hop_size,
        sample_rate,
        whole_audio=False,
        volume_aug=False
    ):
        super().__init__()
        
        self.waveform_sec = waveform_sec
        self.sample_rate = sample_rate
        self.hop_size = hop_size
        self.path_root = path_root
        self.paths = traverse_dir(
            os.path.join(path_root, 'audio'),
            extension='wav',
            is_pure=True,
            is_sort=True,
            is_ext=False
        )
        self.whole_audio = whole_audio
        self.volume_aug = volume_aug

    def __getitem__(self, file_idx):
        name = self.paths[file_idx]

        # check duration. if too short, then skip
        duration = librosa.get_duration(
            filename=os.path.join(self.path_root, 'audio', name) + '.wav', 
            sr=self.sample_rate)
            
        if duration < (self.waveform_sec + 0.1):
            return self.__getitem__( (file_idx + 1) % len(self.paths))
        
        # get item
        return self.get_data(name, duration)

    def get_data(self, name, duration):
        # path
        path_audio = os.path.join(self.path_root, 'audio', name) + '.wav'
        path_mel   = os.path.join(self.path_root, 'mel', name) + '.npy'
        path_f0   = os.path.join(self.path_root, 'f0', name) + '.npy'

        # load audio
        frame_resolution = self.hop_size / self.sample_rate
        frame_rate_inv = 1/frame_resolution
        
        waveform_sec = duration if self.whole_audio else self.waveform_sec
        idx_from = 0 if self.whole_audio else random.uniform(0, duration - waveform_sec - 0.1)
        st = int(idx_from*frame_rate_inv)
        idx_from = st*frame_resolution
        
        audio, sr = librosa.load(
                path_audio, 
                sr=self.sample_rate, 
                offset=idx_from,
                duration=waveform_sec)
        
        # clip audio into N seconds
        audio = audio[...,:audio.shape[-1]//self.hop_size*self.hop_size]       
        audio = torch.from_numpy(audio).float()
        
        # load mel
        mel_frame_len = int(waveform_sec*frame_rate_inv)
        audio_mel_ = np.load(path_mel)
        audio_mel = audio_mel_[st:st+mel_frame_len]
        audio_mel = torch.from_numpy(audio_mel).float() 
        
        # load f0
        f0_ = np.load(path_f0)
        f0 = f0_[st:st+mel_frame_len]
        f0_hz = torch.from_numpy(f0).float().unsqueeze(-1)
        
        # volume augmentation
        if self.volume_aug:
            max_amp = float(torch.max(torch.abs(audio))) + 1e-5
            max_shift = min(1, np.log10(1/max_amp))
            log10_mel_shift = random.uniform(-1, max_shift)
            audio *= (10 ** log10_mel_shift)
            audio_mel += log10_mel_shift
        audio_mel = torch.clamp(audio_mel, min=-5)
        
        return dict(audio=audio, f0=f0_hz, mel=audio_mel, name=name)

    def __len__(self):
        return len(self.paths)
