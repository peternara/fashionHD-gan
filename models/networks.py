from __future__ import division, print_function

import torch
import torchvision
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import init
from torch.autograd import Variable
from torch.optim import lr_scheduler

from resnet_wrapper import create_resnet_conv_layers

import numpy as np
import functools

###############################################################################
# Functions
###############################################################################

def weights_init_normal(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.startswith('Conv'):
        init.normal(m.weight.data, 0.0, 0.02)
    elif classname.startswith('Linear'):
        init.normal(m.weight.data, 0.0, 0.02)
    elif classname.startswith('BatchNorm2d'):
        init.normal(m.weight.data, 1.0, 0.02)

    if 'bias' in m._parameters and m.bias is not None:
        init.constant(m.bias.data, 0.0)

def weights_init_normal2(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.startswith('Conv'):
        init.normal(m.weight.data, 0.0, 0.001)
    elif classname.startswith('Linear'):
        init.normal(m.weight.data, 0.0, 0.001)
    elif classname.startswith('BatchNorm2d'):
        init.normal(m.weight.data, 1.0, 0.001)

    if 'bias' in m._parameters and m.bias is not None:
        init.constant(m.bias.data, 0.0)


def weights_init_xavier(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.startswith('Conv'):
        init.xavier_normal(m.weight.data, gain=0.02)
    elif classname.startswith('Linear'):
        init.xavier_normal(m.weight.data, gain=0.02)
    elif classname.startswith('BatchNorm2d'):
        init.normal(m.weight.data, 1.0, 0.02)
    
    if 'bias' in m._parameters and m.bias is not None:
        init.constant(m.bias.data, 0.0)


def weights_init_kaiming(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.startswith('Conv'):
        init.kaiming_normal(m.weight.data, a=0, mode='fan_in')
    elif classname.startswith('Linear'):
        init.kaiming_normal(m.weight.data, a=0, mode='fan_in')
    elif classname.startswith('BatchNorm2d'):
        init.normal(m.weight.data, 1.0, 0.02)

    if 'bias' in m._parameters and m.bias is not None:
        init.constant(m.bias.data, 0.0)


def weights_init_orthogonal(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.startswith('Conv'):
        init.orthogonal(m.weight.data, gain=1)
    elif classname.startswith('Linear'):
        init.orthogonal(m.weight.data, gain=1)
    elif classname.startswith('BatchNorm2d'):
        init.normal(m.weight.data, 1.0, 0.02)
    
    if 'bias' in m._parameters and m.bias is not None:
        init.constant(m.bias.data, 0.0)


def init_weights(net, init_type='normal'):
    # print('initialization method [%s]' % init_type)
    if init_type == 'normal':
        net.apply(weights_init_normal)
    elif init_type == 'normal2':
        net.apply(weights_init_normal2)
    elif init_type == 'xavier':
        net.apply(weights_init_xavier)
    elif init_type == 'kaiming':
        net.apply(weights_init_kaiming)
    elif init_type == 'orthogonal':
        net.apply(weights_init_orthogonal)
    else:
        raise NotImplementedError('initialization method [%s] is not implemented' % init_type)

###############################################################################
# Loss Functions
###############################################################################
class LossBuffer():
    '''
    '''
    def __init__(self):
        self.clear()
    
    def clear(self):
        self.buffer = []

    def add(self, loss):

        if isinstance(loss, Variable):
            self.buffer.append(loss.data[0])
        elif isinstance(loss, torch.tensor._TensorBase):
            self.buffer.append(loss[0])
        else:
            self.buffer.append(loss)

    def smooth_loss(self, clear = False):
        if len(self.buffer) == 0:
            loss = 0
        else:
            loss = sum(self.buffer) / len(self.buffer)

        if clear:
            self.clear()
            
        return loss


class Smooth_Loss():
    '''
    wrapper of pytorch loss layer.
    '''

    def __init__(self, crit):
        self.crit = crit
        self.clear()

    def __call__(self, input_1, input_2, *extra_input):
        loss = self.crit(input_1, input_2, *extra_input)
        self.weight_buffer.append(input_1.size(0))

        if isinstance(loss, Variable):
            self.buffer.append(loss.data[0])
        elif isinstance(loss, torch.tensor._TensorBase):
            self.buffer.append(loss[0])
        else:
            self.buffer.append(loss)

        return loss

    def clear(self):
        self.buffer = []
        self.weight_buffer = []

    def smooth_loss(self, clear = False):
        if len(self.weight_buffer) == 0:
            loss = 0
        else:
            loss = sum([l * w for l, w in zip(self.buffer, self.weight_buffer)]) / sum(self.weight_buffer)
            
        if clear:
            self.clear()
        return loss

class WeightedBCELoss(nn.Module):
    '''
    Binary Cross Entropy Loss for multilabel classification task. For each class, the positive and negative samples
    have different loss weight according to the positive rates.

    .. math:: loss(o, t) = -1/n \sum_i (t[i] * log(o[i]) * weight_pos[i] + (1-t[i]) * log(1 - o[i]) * weight_neg[i])
    

    Args:
        pos_rate (Tensor): positive rate of each class. This will be used to compute the pos/neg loss weight for each class
        class_norm (bool): normalize loss in each class if true. otherwise normalize loss over all classes

    Shape:
        - Input: (N, *)
        - Target: (N, *)

    '''

    def __init__(self, pos_rate, class_norm = True, size_average = True):
        super(WeightedBCELoss, self).__init__()
        self.class_norm = class_norm
        self.size_average = size_average
        self.register_buffer('w_pos', Variable(0.5 / pos_rate))
        self.register_buffer('w_neg', Variable(0.5 / (1-pos_rate)))

    def forward(self, input, target):
        assert not target.requires_grad, 'criterions do not compute the gradient w.r.t. targets - please'\
        'mark these variables as volatile or not requiring gradients'
        
        # if not (isinstance(self.w_pos, Variable) and isinstance(self.w_neg, Variable)):
        #     self.w_pos = target.data.new(self.w_pos.size()).copy_(self.w_pos)
        #     self.w_neg = target.data.new(self.w_neg.size()).copy_(self.w_net)

        w_mask = target * self.w_pos + (1-target) * self.w_neg
        input = input.clamp(min = 1e-7, max = 1-1e-7)
        loss = -target * input.log() - (1-target) * (1-input).log()
        loss = loss * w_mask

        if self.class_norm:
            loss = loss / w_mask.mean(dim = 0)
        else:
            loss = loss / w_mask.mean()

        if self.size_average:
            return loss.mean()
        else:
            return loss.sum()
    
###############################################################################
# Metrics
###############################################################################

class MeanAP():
    '''
    compute meanAP
    '''

    def __init__(self):
        self.clear()

    def clear(self):
        self.score = None
        self.label = None

    def add(self, new_score, new_label):

        inputs = [new_score, new_label]

        for i in range(len(inputs)):

            if isinstance(inputs[i], list):
                inputs[i] = np.array(inputs[i], dtype = np.float32)

            elif isinstance(inputs[i], np.ndarray):
                inputs[i] = inputs[i].astype(np.float32)

            elif isinstance(inputs[i], torch.tensor._TensorBase):
                inputs[i] = inputs[i].cpu().numpy().astype(np.float32)

            elif isinstance(inputs[i], Variable):
                inputs[i] = inputs[i].data.cpu().numpy().astype(np.float32)

        new_score, new_label = inputs
        assert new_score.shape == new_label.shape, 'shape mismatch: %s vs. %s' % (new_score.shape, new_label.shape)

        self.score = np.concatenate((self.score, new_score), axis = 0) if self.score is not None else new_score
        self.label = np.concatenate((self.label, new_label), axis = 0) if self.label is not None else new_label

    def compute_mean_ap(self):

        score, label = self.score, self.label

        assert score is not None and label is not None
        assert score.shape == label.shape, 'shape mismatch: %s vs. %s' % (score.shape, label.shape)
        assert(score.ndim == 2)
        M, N = score.shape[0], score.shape[1]

        # compute tp: column n in tp is the n-th class label in descending order of the sample score.
        index = np.argsort(score, axis = 0)[::-1, :]
        tp = label.copy().astype(np.float)
        for i in xrange(N):
            tp[:, i] = tp[index[:,i], i]
        tp = tp.cumsum(axis = 0)

        m_grid, n_grid = np.meshgrid(range(M), range(N), indexing = 'ij')
        tp_add_fp = m_grid + 1    
        num_truths = np.sum(label, axis = 0)
        # compute recall and precise
        rec = tp / num_truths
        prec = tp / tp_add_fp

        prec = np.append(np.zeros((1,N), dtype = np.float), prec, axis = 0)
        for i in xrange(M-1, -1, -1):
            prec[i, :] = np.max(prec[i:i+2, :], axis = 0)
        rec_1 = np.append(np.zeros((1,N), dtype = np.float), rec, axis = 0)
        rec_2 = np.append(rec, np.ones((1,N), dtype = np.float), axis = 0)
        AP = np.sum(prec * (rec_2 - rec_1), axis = 0)
        AP[np.isnan(AP)] = -1 # avoid error caused by classes that have no positive sample

        assert((AP <= 1).all())

        AP = AP * 100.
        meanAP = AP[AP >= 0].mean()

        return meanAP, AP

    def compute_recall(self, k = 3):
        score, label = self.score, self.label

        # for each sample, assigned attributes with top-k socre as its tags
        tag = np.where((-score).argsort().argsort() < k, 1, 0)
        tag_rec = tag * label

        rec_overall = tag_rec.sum() / label.sum() * 100.
        rec_class = (tag_rec.sum(axis=0) / label.sum(axis=0))*100.
        rec_class_avg = rec_class.mean()

        return rec_class_avg, rec_class, rec_overall


    def compute_balanced_precision(self):
        '''
        compute the average of true-positive-rate and true-negative-rate
        '''

        score, label = self.score, self.label

        assert score is not None and label is not None
        assert score.shape == label.shape, 'shape mismatch: %s vs. %s' % (score.shape, label.shape)
        assert(score.ndim == 2)

        # compute true-positive and true-negative
        tp = np.where(np.logical_and(score > 0.5, label == 1), 1, 0)
        tn = np.where(np.logical_and(score < 0.5, label == 0), 1, 0)

        # compute average precise
        p_pos = tp.sum(axis = 0) / (label == 1).sum(axis = 0)
        p_neg = tn.sum(axis = 0) / (label == 0).sum(axis = 0)

        BP = (p_pos + p_neg) / 2

        BP = BP * 100.
        mBP = BP.mean()

        return mBP, BP

    def compute_recall_sample_avg(self, k = 3):
        '''
        compute recall using method in DeepFashion Paper
        '''
        score, label = self.score, self.label
        tag = np.where((-score).argsort().argsort() < k, 1, 0)
        tag_rec = tag * label

        count_rec = tag_rec.sum(axis = 1)
        count_gt = label.sum(axis = 1)

        # set recall=1 for sample with no positive attribute label
        no_pos_attr = (count_gt == 0).astype(count_gt.dtype)
        count_rec += no_pos_attr
        count_gt += no_pos_attr

        rec = (count_rec / count_gt).mean() * 100.

        return rec

class ClassificationAccuracy():
    '''
    compute meanAP
    '''
    def __init__(self):
        self.clear()

    def clear(self):
        self.score = None
        self.label = None

    def add(self, new_score, new_label):

        inputs = [new_score, new_label]

        for i in range(len(inputs)):

            if isinstance(inputs[i], list):
                inputs[i] = np.array(inputs[i], dtype = np.float32)

            elif isinstance(inputs[i], np.ndarray):
                inputs[i] = inputs[i].astype(np.float32)

            elif isinstance(inputs[i], torch.tensor._TensorBase):
                inputs[i] = inputs[i].cpu().numpy().astype(np.float32)

            elif isinstance(inputs[i], Variable):
                inputs[i] = inputs[i].data.cpu().numpy().astype(np.float32)

        new_score, new_label = inputs
        assert new_score.shape[0] == new_label.shape[0], 'shape mismatch: %s vs. %s' % (new_score.shape, new_label.shape)
        assert new_label.max() < new_score.shape[1], 'invalid label value %f' % new_label.max()

        new_label = new_label.flatten()
        self.score = np.concatenate((self.score, new_score), axis = 0) if self.score is not None else new_score
        self.label = np.concatenate((self.label, new_label), axis = 0) if self.label is not None else new_label

    def compute_accuracy(self, k = 1):
        score = self.score
        label = self.label

        num_sample = score.shape[0]
        label_one_hot = np.zeros(score.shape)
        label_one_hot[np.arange(num_sample), label.astype(np.int)] = 1
        pred_k_hot = np.where((-score).argsort().argsort() < k, 1, 0)

        num_hit = (pred_k_hot * label_one_hot).sum()
        return num_hit / num_sample * 100.


###############################################################################
# Optimizer and Scheduler
###############################################################################

def get_scheduler(optimizer, opt):
    if opt.lr_policy == 'lambda':
        def lambda_rule(epoch):
            lr_l = 1.0 - max(0, epoch + 1 + opt.epoch_count - opt.niter) / float(opt.niter_decay + 1)
            return lr_l
        scheduler = lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda_rule)
    elif opt.lr_policy == 'step':
        scheduler = lr_scheduler.StepLR(optimizer, step_size=opt.lr_decay, gamma=opt.lr_gamma)
    elif opt.lr_policy == 'plateau':
        scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.2, threshold=0.01, patience=5)
    else:
        return NotImplementedError('learning rate policy [%s] is not implemented', opt.lr_policy)
    return scheduler


###############################################################################
# GAN
###############################################################################

def define_G(opt):

    netG = None
    use_gpu = len(opt.gpu_ids) > 0
    norm_layer = get_norm_layer(norm_type=opt.norm)
    activation  = nn.ReLU
    use_dropout = not opt.no_dropout
    if opt.attr_condition_type in {'feat', 'feat_map'}:
        attr_nc = opt.n_attr_feat
    elif opt.attr_condition_type in {'prob', 'prob_map'}:
        attr_nc = opt.n_attr

    # Todo: add choice of activation function
    if use_gpu:
        assert(torch.cuda.is_available())

    if not opt.no_attr_condition:
        if opt.which_model_netG == 'resnet_9blocks':
            netG = ConditionedResnetGenerator(input_nc = opt.G_input_nc, output_nc = opt.G_output_nc, condition_nc = attr_nc,
                condition_layer = opt.G_condition_layer, ngf = opt.ngf, norm_layer = norm_layer, activation = activation,
                use_dropout = use_dropout, n_blocks = 9, gpu_ids = opt.gpu_ids)
        elif opt.which_model_netG == 'resnet_6blocks':
            netG = ConditionedResnetGenerator(input_nc = opt.G_input_nc, output_nc = opt.G_output_nc, condition_nc = attr_nc,
                condition_layer = opt.G_condition_layer, ngf = opt.ngf, norm_layer = norm_layer, activation = activation,
                use_dropout = use_dropout, n_blocks = 6, gpu_ids = opt.gpu_ids)
        else:
            raise NotImplementedError('Generator model name [%s] is not recognized' % opt.which_model_netG)    
    else:
        if opt.which_model_netG == 'resnet_9blocks':
            netG = ResnetGenerator(input_nc = opt.G_input_nc, output_nc = opt.G_output_nc,
                condition_layer = opt.G_condition_layer, ngf = opt.ngf, norm_layer = norm_layer,
                use_dropout = use_dropout, n_blocks = 9, gpu_ids = opt.gpu_ids)
        elif opt.which_model_netG == 'resnet_6blocks':
            netG = ResnetGenerator(input_nc = opt.G_input_nc, output_nc = opt.G_output_nc,
                condition_layer = opt.G_condition_layer, ngf = opt.ngf, norm_layer = norm_layer,
                use_dropout = use_dropout, n_blocks = 6, gpu_ids = opt.gpu_ids)
        else:
            raise NotImplementedError('Generator model name [%s] is not recognized' % opt.which_model_netG)    

    # if which_model_netG == 'resnet_9blocks':
    #     netG = ResnetGenerator(input_nc, output_nc, ngf, norm_layer=norm_layer, use_dropout=use_dropout, n_blocks=9, gpu_ids=gpu_ids)
    # elif which_model_netG == 'resnet_6blocks':
    #     netG = ResnetGenerator(input_nc, output_nc, ngf, norm_layer=norm_layer, use_dropout=use_dropout, n_blocks=6, gpu_ids=gpu_ids)
    # elif which_model_netG == 'unet_128':
    #     netG = UnetGenerator(input_nc, output_nc, 7, ngf, norm_layer=norm_layer, use_dropout=use_dropout, gpu_ids=gpu_ids)
    # elif which_model_netG == 'unet_256':
    #     netG = UnetGenerator(input_nc, output_nc, 8, ngf, norm_layer=norm_layer, use_dropout=use_dropout, gpu_ids=gpu_ids)
    # else:
    #     raise NotImplementedError('Generator model name [%s] is not recognized' % which_model_netG)

    if len(opt.gpu_ids) > 0:
        netG.cuda(opt.gpu_ids[0])
    init_weights(netG, init_type=opt.init_type)
    return netG


# def define_D(input_nc, ndf, which_model_netD,
#              n_layers_D=3, norm='batch', use_sigmoid=False, init_type='normal', gpu_ids=[]):
def define_D(opt):
    netD = None
    use_gpu = len(opt.gpu_ids) > 0
    use_sigmoid = opt.no_lsgan
    norm_layer = get_norm_layer(norm_type=opt.norm)

    if use_gpu:
        assert(torch.cuda.is_available())

    if opt.which_model_netD == 'basic':
        netD = NLayerDiscriminator(input_nc = opt.D_input_nc, ndf = opt.ndf, n_layers=3, norm_layer=norm_layer, use_sigmoid=use_sigmoid, gpu_ids=opt.gpu_ids)
    elif opt.which_model_netD == 'n_layers':
        netD = NLayerDiscriminator(input_nc = opt.D_input_nc, ndf = opt.ndf, n_layers=opt.n_layers_D, norm_layer=norm_layer, use_sigmoid=use_sigmoid, gpu_ids=opt.gpu_ids)
    elif opt.which_model_netD == 'pixel':
        netD = PixelDiscriminator(input_nc = opt.D_input_nc, ndf = opt.ndf, norm_layer=norm_layer, use_sigmoid=use_sigmoid, gpu_ids=opt.gpu_ids)
    else:
        raise NotImplementedError('Discriminator model name [%s] is not recognized' %
                                  opt.which_model_netD)
    if use_gpu:
        netD.cuda(opt.gpu_ids[0])
    init_weights(netD, init_type=opt.init_type)
    return netD

def print_network(net):
    num_params = 0
    for param in net.parameters():
        num_params += param.numel()
    print(net)
    print('Total number of parameters: %d' % num_params)


# Defines the GAN loss which uses either LSGAN or the regular GAN.
# When LSGAN is used, it is basically same as MSELoss,
# but it abstracts away the need to create the target label tensor
# that has the same size as the input
class GANLoss(nn.Module):
    def __init__(self, use_lsgan=True, target_real_label=1.0, target_fake_label=0.0,
                 tensor=torch.FloatTensor):
        super(GANLoss, self).__init__()
        self.real_label = target_real_label
        self.fake_label = target_fake_label
        self.real_label_var = None
        self.fake_label_var = None
        self.Tensor = tensor
        if use_lsgan:
            self.loss = nn.MSELoss()
        else:
            self.loss = nn.BCELoss()

    def get_target_tensor(self, input, target_is_real):
        target_tensor = None
        if target_is_real:
            create_label = ((self.real_label_var is None) or
                            (self.real_label_var.numel() != input.numel()))
            if create_label:
                # real_tensor = self.Tensor(input.size()).fill_(self.real_label)
                real_tensor = input.data.new(input.size()).fill_(self.real_label)
                self.real_label_var = Variable(real_tensor, requires_grad=False)
            target_tensor = self.real_label_var
        else:
            create_label = ((self.fake_label_var is None) or
                            (self.fake_label_var.numel() != input.numel()))
            if create_label:
                # fake_tensor = self.Tensor(input.size()).fill_(self.fake_label)
                fake_tensor = input.data.new(input.size()).fill_(self.fake_label)
                self.fake_label_var = Variable(fake_tensor, requires_grad=False)
            target_tensor = self.fake_label_var
        return target_tensor

    def __call__(self, input, target_is_real):
        target_tensor = self.get_target_tensor(input, target_is_real)
        return self.loss(input, target_tensor)

def get_norm_layer(norm_type = 'instance'):
    if norm_type == 'batch':
        norm_layer = functools.partial(nn.BatchNorm2d, affine=True)
    elif norm_type == 'instance':
        norm_layer = functools.partial(nn.InstanceNorm2d, affine =False)
    elif norm_type == 'none':
        norm_layer = None
    else:
        raise NotImplementedError('normalization layer [%s] is not found' % norm_type)
    return norm_layer


# Define a resnet block
class ResnetBlock(nn.Module):
    def __init__(self, dim, padding_type, norm_layer, use_bias, activation=nn.ReLU(True), use_dropout=False):
        super(ResnetBlock, self).__init__()
        self.dim = dim
        self.conv_block = self.build_conv_block(dim, padding_type, norm_layer, activation, use_dropout, use_bias)

    def build_conv_block(self, dim, padding_type, norm_layer, activation, use_dropout, use_bias):
        conv_block = []
        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)

        conv_block += [nn.Conv2d(dim, dim, kernel_size=3, padding=p, bias=use_bias),
                       norm_layer(dim),
                       activation]
        if use_dropout:
            conv_block += [nn.Dropout(0.5)]

        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)
        conv_block += [nn.Conv2d(dim, dim, kernel_size=3, padding=p, bias=use_bias),
                       norm_layer(dim)]

        return nn.Sequential(*conv_block)

    def forward(self, x):
        out = x + self.conv_block(x)
        return out

    def print(self):
        print('ResnetBlock: x_dim=%d'%self.dim)

class ResnetGenerator(nn.Module):
    def __init__(self, input_nc, output_nc, ngf=64, norm_layer=nn.BatchNorm2d, activation = nn.ReLU, use_dropout=False, n_blocks=6, gpu_ids=[], padding_type='reflect'):
        assert(n_blocks >= 0)
        super(ResnetGenerator, self).__init__()
        self.input_nc = input_nc
        self.output_nc = output_nc
        self.ngf = ngf
        self.gpu_ids = gpu_ids

        if type(norm_layer) == functools.partial:
            use_bias = norm_layer.func == nn.InstanceNorm2d
        else:
            use_bias = norm_layer == nn.InstanceNorm2d

        model = [nn.ReflectionPad2d(3),
                 nn.Conv2d(input_nc, ngf, kernel_size=7, padding=0,
                           bias=use_bias),
                 norm_layer(ngf),
                 activation()]

        n_downsampling = 2
        for i in range(n_downsampling):
            mult = 2**i
            model += [nn.Conv2d(ngf * mult, ngf * mult * 2, kernel_size=3,
                                stride=2, padding=1, bias=use_bias),
                      norm_layer(ngf * mult * 2),
                      activation()]

        mult = 2**n_downsampling
        for i in range(n_blocks):
            model += [ResnetBlock(ngf * mult, padding_type=padding_type, activation = activation(), norm_layer=norm_layer, use_dropout=use_dropout, use_bias=use_bias)]

        for i in range(n_downsampling):
            mult = 2**(n_downsampling - i)
            model += [nn.ConvTranspose2d(ngf * mult, int(ngf * mult / 2),
                                         kernel_size=3, stride=2,
                                         padding=1, output_padding=1,
                                         bias=use_bias),
                      norm_layer(int(ngf * mult / 2)),
                      activation()]

        model += [nn.ReflectionPad2d(3)]
        model += [nn.Conv2d(ngf, output_nc, kernel_size=7, padding=0)]
        model += [nn.Tanh()]

        self.model = nn.Sequential(*model)

    def forward(self, input):
        if self.gpu_ids and isinstance(input.data, torch.cuda.FloatTensor):
            return nn.parallel.data_parallel(self.model, input, self.gpu_ids)
        else:
            return self.model(input)

class ConditionedResnetBlock(nn.Module):
    def __init__(self, x_dim, c_dim, padding_type, norm_layer, use_bias, activation=nn.ReLU(True), use_dropout=False, output_c=False):
        '''
        Args:
            x_dim(int): input feature channel
            c_dim(int): condition feature channel
            output_c(bool): whether concat condition feature to the outout
        Input:
            x(Variable): size of (bsz, x_dim+c_dim, h, w)
        Output:
            y(Variable): size of (bsz, x_dim+c_dim, h, w) if output_c is true, else (bsz, x_dim, h, w)
        '''
        super(ConditionedResnetBlock, self).__init__()
        self.conv_block = self.build_conv_block(x_dim, c_dim, padding_type, norm_layer, activation, use_dropout, use_bias)
        self.output_c = output_c
        self.x_dim = x_dim
        self.c_dim = c_dim

    def build_conv_block(self, x_dim, c_dim, padding_type, norm_layer, activation, use_dropout, use_bias):
        conv_block = []

        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)

        conv_block += [nn.Conv2d(x_dim + c_dim, x_dim, kernel_size=3, padding=p, bias=use_bias),
                       norm_layer(x_dim),
                       activation]
        if use_dropout:
            conv_block += [nn.Dropout(0.5)]

        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)
        conv_block += [nn.Conv2d(x_dim, x_dim, kernel_size=3, padding=p, bias=use_bias),
                       norm_layer(x_dim)]

        return nn.Sequential(*conv_block)

    def forward(self, x_and_c):
        # out = x + self.conv_block(x)
        x = x_and_c[:,0:self.x_dim]
        c = x_and_c[:,self.x_dim::]
        x_out = x + self.conv_block(x_and_c)
        if self.output_c:
            return torch.cat((x_out, c), dim = 1)
        else:
            return x_out

    def print(self):
        out_dim = self.x_dim + self.c_dim if self.output_c else self.x_dim
        print('ConditionResnetBlock: x_dim=%d, c_dim=%d, out_dim=%d'% (self.x_dim, self.c_dim, out_dim))

class ConditionedResnetGenerator(nn.Module):
    def __init__(self, input_nc, output_nc, condition_nc, condition_layer = 'first', ngf=64, norm_layer=nn.BatchNorm2d, activation = nn.ReLU, use_dropout=False, n_blocks=6, gpu_ids=[], padding_type='reflect'):
        assert(n_blocks >= 0)
        super(ConditionedResnetGenerator, self).__init__()
        self.input_nc = input_nc
        self.output_nc = output_nc
        self.ngf = ngf
        self.condition_nc = condition_nc
        self.condition_layer = condition_layer
        self.gpu_ids = gpu_ids
        if type(norm_layer) == functools.partial:
            use_bias = norm_layer.func == nn.InstanceNorm2d
        else:
            use_bias = norm_layer == nn.InstanceNorm2d

        downsample_layers = [
            nn.ReflectionPad2d(3),
            nn.Conv2d(input_nc, ngf, kernel_size=7, padding=0, bias=use_bias),
            norm_layer(ngf),
            activation()]

        n_downsampling = 2
        for i in range(n_downsampling):
            mult = 2**i
            downsample_layers += [
                nn.Conv2d(ngf*mult, ngf*mult*2, kernel_size = 3, stride = 2, padding = 1, bias = use_bias),
                norm_layer(ngf*mult*2),
                activation()
            ]

        res_blocks = []
        mult = 2**n_downsampling
        for i in range(n_blocks):
            if (condition_layer == 'first' and i == 0) or condition_layer == 'all':
                output_c = (condition_layer == 'all' and i < n_blocks - 1)
                res_blocks.append(ConditionedResnetBlock(
                    x_dim = ngf*mult,
                    c_dim = condition_nc, 
                    padding_type=padding_type,
                    activation = activation(),
                    norm_layer = norm_layer,
                    use_dropout = use_dropout,
                    output_c = output_c,
                    use_bias = use_bias
                    ))
            else:
                res_blocks.append(ResnetBlock(
                    dim = ngf*mult,
                    padding_type=padding_type,
                    activation = activation(),
                    norm_layer = norm_layer,
                    use_dropout = use_dropout,
                    use_bias = use_bias
                    ))

        upsample_layers = []
        for i in range(n_downsampling):
            mult = 2**(n_downsampling-i)
            upsample_layers += [
                nn.ConvTranspose2d(ngf*mult, int(ngf*mult/2), kernel_size = 3, stride = 2, padding = 1, output_padding = 1, bias = use_bias),
                norm_layer(int(ngf * mult / 2)),
                activation()
            ]
        upsample_layers += [
            nn.ReflectionPad2d(3),
            nn.Conv2d(ngf, output_nc, kernel_size = 7, padding = 0),
            nn.Tanh()
        ]


        self.down_sample = nn.Sequential(*downsample_layers)
        self.res_blocks = nn.Sequential(*res_blocks)
        self.up_sample = nn.Sequential(*upsample_layers)

    
    def forward(self, input_x, input_c, single_device = False):
        '''
        Input:
            input_x: size of (bsz, input_nc, h, w)
            input_c: size of (bsz, condition_nc) or (bsz, condition_nc, h_r, w_r)
        '''
        if self.gpu_ids and len(self.gpu_ids) > 1 and isinstance(input_x.data, torch.cuda.FloatTensor) and (not single_device):
            return nn.parallel.data_parallel(self, (input_x, input_c), self.gpu_ids, module_kwargs = {'single_device': True})
        else:
            x = self.down_sample(input_x)
            bsz, _, h_x, w_x = x.size()

            if input_c.dim() == 2:
                c = input_c.view(bsz, self.condition_nc, 1, 1).expand(bsz, self.condition_nc, h_x, w_x)
            elif input_c.dim() == 4:
                c = F.upsample(input_c, size = (h_x, w_x), mode = 'bilinear')

            x = self.res_blocks(torch.cat((x, c), dim = 1))
            x = self.up_sample(x)

            return x



class UnetSkipConnectionBlock(nn.Module):
    def __init__(self, outer_nc, inner_nc, input_nc=None,
                 submodule=None, outermost=False, innermost=False, norm_layer=nn.BatchNorm2d, use_dropout=False):
        super(UnetSkipConnectionBlock, self).__init__()
        self.outermost = outermost
        if type(norm_layer) == functools.partial:
            use_bias = norm_layer.func == nn.InstanceNorm2d
        else:
            use_bias = norm_layer == nn.InstanceNorm2d
        if input_nc is None:
            input_nc = outer_nc
        downconv = nn.Conv2d(input_nc, inner_nc, kernel_size=4,
                             stride=2, padding=1, bias=use_bias)
        downrelu = nn.LeakyReLU(0.2, True)
        downnorm = norm_layer(inner_nc)
        uprelu = nn.ReLU(True)
        upnorm = norm_layer(outer_nc)

        if outermost:
            upconv = nn.ConvTranspose2d(inner_nc * 2, outer_nc,
                                        kernel_size=4, stride=2,
                                        padding=1)
            down = [downconv]
            up = [uprelu, upconv, nn.Tanh()]
            model = down + [submodule] + up
        elif innermost:
            upconv = nn.ConvTranspose2d(inner_nc, outer_nc,
                                        kernel_size=4, stride=2,
                                        padding=1, bias=use_bias)
            down = [downrelu, downconv]
            up = [uprelu, upconv, upnorm]
            model = down + up
        else:
            upconv = nn.ConvTranspose2d(inner_nc * 2, outer_nc,
                                        kernel_size=4, stride=2,
                                        padding=1, bias=use_bias)
            down = [downrelu, downconv, downnorm]
            up = [uprelu, upconv, upnorm]

            if use_dropout:
                model = down + [submodule] + up + [nn.Dropout(0.5)]
            else:
                model = down + [submodule] + up

        self.model = nn.Sequential(*model)

    def forward(self, x):
        if self.outermost:
            return self.model(x)
        else:
            return torch.cat([x, self.model(x)], 1)

# Defines the Unet generator.
# |num_downs|: number of downsamplings in UNet. For example,
# if |num_downs| == 7, image of size 128x128 will become of size 1x1
# at the bottleneck
class UnetGenerator(nn.Module):
    def __init__(self, input_nc, output_nc, num_downs, ngf=64,
                 norm_layer=nn.BatchNorm2d, use_dropout=False, gpu_ids=[]):
        super(UnetGenerator, self).__init__()
        self.gpu_ids = gpu_ids

        # construct unet structure
        unet_block = UnetSkipConnectionBlock(ngf * 8, ngf * 8, input_nc=None, submodule=None, norm_layer=norm_layer, innermost=True)
        for i in range(num_downs - 5):
            unet_block = UnetSkipConnectionBlock(ngf * 8, ngf * 8, input_nc=None, submodule=unet_block, norm_layer=norm_layer, use_dropout=use_dropout)
        unet_block = UnetSkipConnectionBlock(ngf * 4, ngf * 8, input_nc=None, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(ngf * 2, ngf * 4, input_nc=None, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(ngf, ngf * 2, input_nc=None, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(output_nc, ngf, input_nc=input_nc, submodule=unet_block, outermost=True, norm_layer=norm_layer)

        self.model = unet_block

    def forward(self, input):
        if self.gpu_ids and isinstance(input.data, torch.cuda.FloatTensor):
            return nn.parallel.data_parallel(self.model, input, self.gpu_ids)
        else:
            return self.model(input)



# Defines the PatchGAN discriminator with the specified arguments.
class NLayerDiscriminator(nn.Module):
    def __init__(self, input_nc, ndf=64, n_layers=3, norm_layer=nn.BatchNorm2d, use_sigmoid=False, gpu_ids=[]):
        super(NLayerDiscriminator, self).__init__()
        self.gpu_ids = gpu_ids
        if type(norm_layer) == functools.partial:
            use_bias = norm_layer.func == nn.InstanceNorm2d
        else:
            use_bias = norm_layer == nn.InstanceNorm2d

        kw = 4
        padw = 1
        sequence = [
            nn.Conv2d(input_nc, ndf, kernel_size=kw, stride=2, padding=padw),
            nn.LeakyReLU(0.2, True)
        ]

        nf_mult = 1
        nf_mult_prev = 1
        for n in range(1, n_layers):
            nf_mult_prev = nf_mult
            nf_mult = min(2**n, 8)
            sequence += [
                nn.Conv2d(ndf * nf_mult_prev, ndf * nf_mult,
                          kernel_size=kw, stride=2, padding=padw, bias=use_bias),
                norm_layer(ndf * nf_mult),
                nn.LeakyReLU(0.2, True)
            ]

        nf_mult_prev = nf_mult
        nf_mult = min(2**n_layers, 8)
        sequence += [
            nn.Conv2d(ndf * nf_mult_prev, ndf * nf_mult,
                      kernel_size=kw, stride=1, padding=padw, bias=use_bias),
            norm_layer(ndf * nf_mult),
            nn.LeakyReLU(0.2, True)
        ]

        sequence += [nn.Conv2d(ndf * nf_mult, 1, kernel_size=kw, stride=1, padding=padw)]

        if use_sigmoid:
            sequence += [nn.Sigmoid()]

        self.model = nn.Sequential(*sequence)

    def forward(self, input):
        if len(self.gpu_ids) and isinstance(input.data, torch.cuda.FloatTensor):
            return nn.parallel.data_parallel(self.model, input, self.gpu_ids)
        else:
            return self.model(input)



class PixelDiscriminator(nn.Module):
    def __init__(self, input_nc, ndf=64, norm_layer=nn.BatchNorm2d, use_sigmoid=False, gpu_ids=[]):
        super(PixelDiscriminator, self).__init__()
        self.gpu_ids = gpu_ids
        if type(norm_layer) == functools.partial:
            use_bias = norm_layer.func == nn.InstanceNorm2d
        else:
            use_bias = norm_layer == nn.InstanceNorm2d
            
        self.net = [
            nn.Conv2d(input_nc, ndf, kernel_size=1, stride=1, padding=0),
            nn.LeakyReLU(0.2, True),
            nn.Conv2d(ndf, ndf * 2, kernel_size=1, stride=1, padding=0, bias=use_bias),
            norm_layer(ndf * 2),
            nn.LeakyReLU(0.2, True),
            nn.Conv2d(ndf * 2, 1, kernel_size=1, stride=1, padding=0, bias=use_bias)]

        if use_sigmoid:
            self.net.append(nn.Sigmoid())

        self.net = nn.Sequential(*self.net)

    def forward(self, input):
        if len(self.gpu_ids) and isinstance(input.data, torch.cuda.FloatTensor):
            return nn.parallel.data_parallel(self.net, input, self.gpu_ids)
        else:
            return self.net(input)

###############################################################################
# Attribute
###############################################################################

def define_attr_encoder_net(opt):
    if opt.joint_cat:
        if opt.spatial_pool != 'none' or opt.input_lm:
            raise NotImplementedError()
        if opt.spatial_pool == 'none':
            net = JointNoneSpatialAttributeEncoderNet(
                convnet = opt.convnet,
                input_nc = opt.input_nc,
                output_nc = opt.n_attr,
                output_nc1 = opt.n_cat,
                feat_norm = opt.feat_norm,
                gpu_ids = opt.gpu_ids,
                init_type = opt.init_type)
    else:
        if opt.input_lm:
            if opt.spatial_pool == 'none':
                raise NotImplementedError()
            else:
                net = DualSpatialAttributeEncoderNet(
                    convnet = opt.convnet,
                    spatial_pool = opt.spatial_pool,
                    input_nc = opt.input_nc,
                    output_nc = opt.n_attr,
                    lm_input_nc = opt.lm_input_nc,
                    lm_output_nc = opt.lm_output_nc,
                    lm_fusion = opt.lm_fusion,
                    feat_norm = opt.feat_norm,
                    gpu_ids = opt.gpu_ids,
                    init_type = opt.init_type)
        else:
            if opt.spatial_pool == 'none':
                net = NoneSpatialAttributeEncoderNet(
                    convnet = opt.convnet,
                    input_nc = opt.input_nc,
                    output_nc = opt.n_attr,
                    feat_norm = opt.feat_norm,
                    gpu_ids = opt.gpu_ids,
                    init_type = opt.init_type)
            elif opt.spatial_pool in {'max', 'noisyor'}:
                net = SpatialAttributeEncoderNet(
                    convnet = opt.convnet,
                    spatial_pool = opt.spatial_pool,
                    input_nc = opt.input_nc, 
                    output_nc = opt.n_attr,
                    feat_norm = opt.feat_norm,
                    gpu_ids = opt.gpu_ids,
                    init_type = opt.init_type)

    if len(opt.gpu_ids) > 0:
        net.cuda(opt.gpu_ids[0])

    return net



class NoisyOR(nn.Module):
    def __init__(self):
        super(NoisyOR,self).__init__()

    def forward(self, prob_map):
        bsz, nc, w, h = prob_map.size()
        neg_prob_map = 1 - prob_map.view(bsz, nc, -1)
        neg_prob = Variable(prob_map.data.new(bsz, nc).fill_(1))

        for i in xrange(neg_prob_map.size(2)):
            neg_prob = neg_prob * neg_prob_map[:,:,i]

        return 1 - neg_prob

class LandmarkPool(nn.Module):
    def __init__(self, pool = 'max', region_size = (3,3)):
        super(LandmarkPool, self).__init__()

    def forward(feat_map, lm_list):
        raise NotImplementedError('LandmarkPool.forward not implemented')

        

def create_stack_conv_layers(input_nc, feat_nc_s = 64, feat_nc_f = 1024, num_layer = 5):
    
    c_in = input_nc
    c_out = feat_nc_s
    conv_layers = []

    for n in range(num_layer):
        conv_layers.append(nn.Conv2d(c_in, c_out, 4,2,1, bias = False))
        conv_layers.append(nn.BatchNorm2d(c_out))
        conv_layers.append(nn.ReLU())

        c_in = c_out
        c_out = feat_nc_f if n == num_layer-2 else c_out * 2

    conv = nn.Sequential(*conv_layers)
    conv.output_nc = feat_nc_f

    return conv


class NoneSpatialAttributeEncoderNet(nn.Module):
    def __init__(self, convnet, input_nc, output_nc, feat_norm, gpu_ids, init_type):
        '''
        Args:
            convnet (str): convnet architecture.
            input_nc (int): number of input channels.
            output_nc (int): number of output channels (number of attribute entries)
        '''
        super(NoneSpatialAttributeEncoderNet, self).__init__()
        self.gpu_ids = gpu_ids
        self.feat_norm = feat_norm

        if convnet == 'stackconv':
            pretrain = False
            self.conv = create_stack_conv_layers(input_nc)
        else:
            pretrain = (input_nc == 3)
            self.conv = create_resnet_conv_layers(convnet, input_nc, pretrain)
        self.avgpool = nn.AvgPool2d(7, stride=1)
        self.fc = nn.Linear(self.conv.output_nc, output_nc)

        # initialize weights
        init_weights(self.fc, init_type = init_type)
        if not pretrain:
            init_weights(self.conv, init_type = init_type)

        if pretrain:
            print('load CNN weight pretrained on ImageNet!')


    def forward(self, input_img):
        bsz = input_img.size(0)

        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        feat = self.avgpool(feat_map).view(bsz, -1)
        prob = F.sigmoid(self.fc(feat))

        return prob, None

    def extract_feat(self, input_img):
        bsz = input_img.size(0)

        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        feat = self.avgpool(feat_map).view(bsz, -1)

        return feat, feat_map


class SpatialAttributeEncoderNet(nn.Module):
    def __init__(self, convnet, spatial_pool, input_nc, output_nc, feat_norm, gpu_ids, init_type):
        super(SpatialAttributeEncoderNet, self).__init__()
        self.gpu_ids = gpu_ids
        self.feat_norm = feat_norm

        if convnet == 'stackconv':
            pretrain = False
            self.conv = create_stack_conv_layers(input_nc)
        else:
            pretrain = (input_nc == 3)
            self.conv = create_resnet_conv_layers(convnet, input_nc, pretrain)

        self.cls = nn.Conv2d(self.conv.output_nc, output_nc, kernel_size = 1)

        if spatial_pool == 'max':
            self.pool = nn.MaxPool2d(7, stride=1)
        elif spatial_pool == 'noisyor':
            self.pool = NoisyOR()

        # initialize weights
        init_weights(self.cls, init_type = init_type)
        if spatial_pool == 'noisyor':
            # special initialization
            init.constant(self.cls.bias, -6.58)
            
        if pretrain:
            print('load CNN weight pretrained on ImageNet!')
        else:
            init_weights(self.conv, init_type = init_type)



    def forward(self, input_img):
        bsz = input_img.size(0)
        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        prob_map = F.sigmoid(self.cls(feat_map))
        prob = self.pool(prob_map).view(bsz, -1)

        return prob, prob_map

    def extract_feat(self, input_img):
        bsz = input_img.size(0)
        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)
        feat = F.avg_pool2d(feat_map, kernel_size = 7, stride = 1).view(bsz, -1)

        return feat, feat_map




class DualSpatialAttributeEncoderNet(nn.Module):
    '''
    Attribute Encoder with 2 branches of ConvNet, for RGB image and Landmark heatmap respectively.
    '''
    def __init__(self, convnet, spatial_pool, input_nc, output_nc, lm_input_nc, lm_output_nc, lm_fusion, feat_norm, gpu_ids, init_type):
        super(DualSpatialAttributeEncoderNet, self).__init__()
        # create RGB channel
        self.gpu_ids = gpu_ids
        self.feat_norm = feat_norm
        self.spatial_pool = spatial_pool
        self.fusion = lm_fusion
        if convnet == 'stackconv':
            pretrain = False
            self.conv = create_stack_conv_layers(input_nc)
        else:
            pretrain = (input_nc == 3)
            self.conv = create_resnet_conv_layers(convnet, input_nc, pretrain)
        

        # create landmark channel
        lm_layer_list = []
        c_in = lm_input_nc
        c_out = lm_output_nc // (2**4)

        for n in range(5):
            lm_layer_list.append(nn.Conv2d(c_in, c_out, 4, 2, 1, bias = False))
            lm_layer_list.append(nn.BatchNorm2d(c_out))
            lm_layer_list.append(nn.ReLU())
            c_in = c_out
            c_out *= 2

        self.conv_lm = nn.Sequential(*lm_layer_list)

        # create fusion layers
        if lm_fusion == 'concat':
            feat_nc = self.conv.output_nc + lm_output_nc
            self.cls = nn.Conv2d(feat_nc, output_nc, kernel_size = 1)
        elif lm_fusion == 'linear':
            feat_nc = self.conv.output_nc + lm_output_nc
            self.fuse_layer = nn.Sequential(
                nn.Conv2d(feat_nc, self.conv.output_nc, kernel_size = 1),
                nn.BatchNorm1d(self.conv.output_nc),
                nn.ReLu()
                )
            self.cls = nn.Conv2d(self.conv.output_nc, output_nc, kernel_size = 1)
        else:
            print(lm_fusion)
            raise NotImplementedError()


        # create pooling layers
        if spatial_pool == 'max':
            self.pool = nn.MaxPool2d(7, stride=1)
        elif spatial_pool == 'noisyor':
            self.pool = NoisyOR()

        # initialize weights
        init_weights(self.cls, init_type = init_type)
        init_weights(self.conv_lm, init_type = init_type)
        if lm_fusion == 'linear':
            init_weights(self.fuse_layer, init_type = init_type)
        if spatial_pool == 'noisyor':
            # special initialization
            init.constant(self.cls.bias, -6.58)
            
        if pretrain:
            print('load CNN weight pretrained on ImageNet!')
        else:
            init_weights(self.conv, init_type = init_type)

    def forward(self, input_img, input_lm_heatmap):
        bsz = input_img.size(0)
        if self.gpu_ids:
            img_feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
            lm_feat_map = nn.parallel.data_parallel(self.conv_lm, input_lm_heatmap, self.gpu_ids)
        else:
            img_feat_map = self.conv(input_img)
            lm_feat_map = self.conv_lm(input_lm_heatmap)

        feat_map = None
        if self.fusion == 'concat':
            feat_map = torch.cat((img_feat_map, lm_feat_map), dim = 1)
        elif self.fusion == 'linear':
            feat_map = self.fuse_layer(torch.cat((img_feat_map, lm_feat_map), dim = 1))
        else:
            print(self.fusion)
            raise NotImplementedError()

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)
        
        prob_map = F.sigmoid(self.cls(feat_map))
        prob = self.pool(prob_map).view(bsz, -1)

        return prob, prob_map

    def extract_feat(self, input_img, input_lm_heatmap):
        bsz = input_img.size(0)
        if self.gpu_ids:
            img_feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
            lm_feat_map = nn.parallel.data_parallel(self.conv_lm, input_lm_heatmap, self.gpu_ids)
        else:
            img_feat_map = self.conv(input_img)
            lm_feat_map = self.conv_lm(input_lm_heatmap)

        feat_map = None
        if self.fusion == 'cancat':
            feat_map = torch.cat((img_feat_map, lm_feat_map), dim = 1)
        elif self.fusion == 'linear':
            feat_map = self.fuse_layer(torch.cat((img_feat_map, lm_feat_map), dim = 1))

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        feat = F.avg_pool2d(feat_map, kernel_size = 7, stride = 1).view(bsz, -1)

        return feat, feat_map


class JointNoneSpatialAttributeEncoderNet(nn.Module):
    def __init__(self, convnet, input_nc, output_nc, output_nc1, feat_norm, gpu_ids, init_type):
        '''
        Args:
            convnet (str): convnet architecture.
            input_nc (int): number of input channels.
            output_nc (int): number of output channels (number of attribute entries)
            output_nc1 (int): number of auxiliary output chnnels (number of category entries)
        '''

        super(JointNoneSpatialAttributeEncoderNet, self).__init__()
        self.gpu_ids = gpu_ids
        self.feat_norm = feat_norm

        if convnet == 'stackconv':
            pretrain = False
            self.conv = create_stack_conv_layers(input_nc)
        else:
            pretrain = (input_nc == 3)
            self.conv = create_resnet_conv_layers(convnet, input_nc, pretrain)
        self.avgpool = nn.AvgPool2d(7, stride=1)
        self.fc = nn.Linear(self.conv.output_nc, output_nc)
        self.fc_cat = nn.Linear(self.conv.output_nc, output_nc1)

        # initialize weights
        init_weights(self.fc, init_type = init_type)
        init_weights(self.fc_cat, init_type = init_type)
        if not pretrain:
            init_weights(self.conv, init_type = init_type)

        if pretrain:
            print('load CNN weight pretrained on ImageNet!')

    def forward(self, input_img):
        bsz = input_img.size(0)
        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        feat = self.avgpool(feat_map).view(bsz, -1)
        prob = F.sigmoid(self.fc(feat))
        pred_cat = self.fc_cat(feat)

        return prob, None, pred_cat

    def extract_feat(self, input_img):
        bsz = input_img.size(0)
        if self.gpu_ids:
            feat_map = nn.parallel.data_parallel(self.conv, input_img, self.gpu_ids)
        else:
            feat_map = self.conv(input_img)

        if self.feat_norm:
            feat_map = feat_map / feat_map.norm(p=2, dim=1, keepdim=True)

        feat = self.avgpool(feat_map).view(bsz, -1)

        return feat, feat_map



