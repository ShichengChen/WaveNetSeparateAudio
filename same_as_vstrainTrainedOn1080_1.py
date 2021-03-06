# coding: utf-8

# In[1]:


from __future__ import print_function
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np
import torch.utils.data as utils
import librosa
import soundfile as sf
import time
import os
from torch.utils import data
from wavenet import Wavenet
from transformData import x_mu_law_encode, y_mu_law_encode, mu_law_decode, onehot, cateToSignal
from readDataset import Dataset

# In[2]:


sampleSize = 32000  # the length of the sample size
quantization_channels = 256
sample_rate = 16000
dilations = [2 ** i for i in range(9)] * 5  # idea from wavenet, have more receptive field
residualDim = 168  #
skipDim = 512
shapeoftest = 190500
songnum=20
filterSize = 3
savemusic='./vsCorpus/nus2xtr{}.wav'
resumefile = './model/instrument2'  # name of checkpoint
lossname = 'instrument2loss.txt'  # name of loss file
continueTrain = False  # whether use checkpoint
pad = np.sum(dilations)  # padding for dilate convolutional layers
lossrecord = []  # list for record loss
# pad=0


#     #            |----------------------------------------|     *residual*
#     #            |                                        |
#     #            |    |-- conv -- tanh --|                |
#     # -> dilate -|----|                  * ----|-- 1x1 -- + -->	*input*
#     #                 |-- conv -- sigm --|     |    ||
#     #                                         1x1=residualDim
#     #                                          |
#     # ---------------------------------------> + ------------->	*skip=skipDim*
#     image changed from https://github.com/vincentherrmann/pytorch-wavenet/blob/master/wavenet_model.py

# In[3]:


os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "1"  # use specific GPU

# In[4]:


use_cuda = torch.cuda.is_available()  # whether have available GPU
torch.manual_seed(1)
device = torch.device("cuda" if use_cuda else "cpu")
# device = 'cpu'
# torch.set_default_tensor_type('torch.cuda.FloatTensor') #set_default_tensor_type as cuda tensor
kwargs = {'num_workers': 1, 'pin_memory': True} if use_cuda else {}

# In[5]:


params = {'batch_size': 1, 'shuffle': True, 'num_workers': 1}
training_set = Dataset(np.arange(0, songnum), np.arange(0, songnum), 'ccmixter2/x/', 'ccmixter2/y/')
validation_set = Dataset(np.arange(0, songnum), np.arange(0, songnum), 'ccmixter2/x/', 'ccmixter2/y/')
loadtr = data.DataLoader(training_set, **params)  # pytorch dataloader, more faster than mine
loadval = data.DataLoader(validation_set, **params)

# In[6]:


model = Wavenet(pad, skipDim, quantization_channels, residualDim, dilations).cuda()
criterion = nn.CrossEntropyLoss()
# in wavenet paper, they said crossentropyloss is far better than MSELoss
# optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum)
optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
# use adam to train
# optimizer = optim.SGD(model.parameters(), lr = 0.1, momentum=0.9, weight_decay=1e-5)
# scheduler = StepLR(optimizer, step_size=30, gamma=0.1)
# scheduler = MultiStepLR(optimizer, milestones=[20,40], gamma=0.1)


# In[7]:


if continueTrain:  # if continueTrain, the program will find the checkpoints
    if os.path.isfile(resumefile):
        print("=> loading checkpoint '{}'".format(resumefile))
        checkpoint = torch.load(resumefile)
        start_epoch = checkpoint['epoch']
        # best_prec1 = checkpoint['best_prec1']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        print("=> loaded checkpoint '{}' (epoch {})"
              .format(resumefile, checkpoint['epoch']))
    else:
        print("=> no checkpoint found at '{}'".format(resumefile))


# In[9]:


def test(xtrain,iloader):  # testing data
    model.eval()
    start_time = time.time()
    with torch.no_grad():
        #for iloader, (xtest, _) in enumerate(loadval):
        listofpred = []
        for ind in range(pad, xtrain.shape[-1] - pad, sampleSize):
            output = model(xtrain[:, :, ind - pad:ind + sampleSize + pad].to(device))
            pred = output.max(1, keepdim=True)[1].cpu().numpy().reshape(-1)
            listofpred.append(pred)
        ans = mu_law_decode(np.concatenate(listofpred))
        sf.write(savemusic.format(iloader), ans, sample_rate)
        print('test stored done', time.time() - start_time)


def train(epoch):  # training data, the audio except for last 15 seconds
    model.train()
    for iloader, (xtrain, ytrain) in enumerate(loadtr):
        idx = np.arange(pad, xtrain.shape[-1] - pad - sampleSize, 2000)
        np.random.shuffle(idx)
        lens = idx.shape[-1] // songnum
        idx = idx[:lens]
        for i, ind in enumerate(idx):
            start_time = time.time()
            data, target = xtrain[:, :, ind - pad:ind + sampleSize + pad].to(device), ytrain[:,
                                                                                      ind:ind + sampleSize].to(device)
            output = model(data)
            loss = criterion(output, target)
            lossrecord.append(loss.item())
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            print('Train Epoch: {} iloader:{} [{}/{} ({:.0f}%)] Loss:{:.6f}: , ({:.3f} sec/step)'.format(
                epoch, iloader, i, len(idx), 100. * i / len(idx), loss.item(), time.time() - start_time))
            if i % 100 == 0:
                with open("./lossRecord/" + lossname, "w") as f:
                    for s in lossrecord:
                        f.write(str(s) + "\n")
                print('write finish')

        test(xtrain,iloader)
        state = {'epoch': epoch + 1,
                 'state_dict': model.state_dict(),
                 'optimizer': optimizer.state_dict()}
        if not os.path.exists('./model/'): os.makedirs('./model/')
        torch.save(state, resumefile)


# In[ ]:


for epoch in range(100000):
    train(epoch)
