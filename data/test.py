from __future__ import division, print_function

import torch    
import torchvision
import util.image as image
from util.timer import Timer

def test_AttributeDataset():
    from data_loader import CreateDataLoader
    from options.attribute_options import TrainAttributeOptions, TestAttributeOptions

    timer = Timer()
    
    timer.tic()
    opt = TrainAttributeOptions().parse()
    loader = CreateDataLoader(opt)
    print('cost %.3f sec to create data loader.' % timer.toc())

    loader_iter = iter(loader)
    data = loader_iter.next()

    for k, v in data.iteritems():
        print('data["%s"]: %s' % (k, type(v)))


def test_EXPAttributeDataset():
    from data_loader import CreateDataLoader
    from options.attribute_options import TrainAttributeOptions


    opt = TrainAttributeOptions().parse('--dataset_mode attribute_exp --benchmark debug --batch_size 10')
    loader = CreateDataLoader(opt)
    loader_iter = iter(loader)
    data = loader_iter.next()

    for k, v in data.iteritems():
        print('data["%s"], type: %s' % (k, type(v)))
        try:
            print(v.size())
        except:
            pass

    for idx in range(opt.batch_size):
        # show image
        img = torchvision.utils.make_grid(data['img'], nrow=5, normalize = True).cpu().numpy()
        img = img.transpose([1,2,0])
        img = img[:,:,[2,1,0]] # from RGB to BGR
        image.imshow(img)

        # show heat map
        img = data['img'][idx] # 3xHxW
        lm_maps = data['landmark_heatmap'][idx] # 18xHxW

        print(lm_maps.min())
        print(lm_maps.max())

        img_maps = []
        
        for i in range(lm_maps.size(0)):
            img_map = img * lm_maps[i]
            img_maps.append(img_map)
        img_maps = torch.stack(img_maps)
        img_maps = torchvision.utils.make_grid(img_maps, nrow=9, normalize = True).cpu().numpy()
        img_maps = img_maps.transpose([1,2,0])
        img_maps = img_maps[:,:,[2,1,0]] # from RGB to BGR
        image.imshow(img_maps)

def test_GANDataset():
    from data_loader import CreateDataLoader
    from options.gan_options import TrainGANOptions

    opt = TrainGANOptions().parse('--benchmark debug --batch_size 1')
    loader = CreateDataLoader(opt)
    loader_iter = iter(loader)
    data = loader_iter.next()

    for k, v in data.iteritems():
        if isinstance(v, torch.tensor._TensorBase):
            print('[%s]: (%s), %s' % (k,type(v), v.size()))
        else:
            print('[%s]: %s' % (k, type(v)))

    img = torchvision.utils.make_grid(data['img'], nrow=5, normalize = True).cpu().numpy()
    img = img.transpose([1,2,0])
    img = img[:,:,[2,1,0]] # from RGB to BGR
    if data['seg_mask'].size(1) > 1:
        data['seg_mask'] = data['seg_mask'].max(dim=1, keepdim=True)
    image.imshow(img)
    for idx in range(opt.batch_size):
        
        # show samples
        img = data['img'][idx] # 3xHxW
        lm_maps = data['lm_map'][idx] # 18xHxW

        img_maps = []
        
        img_maps.append(img)
        img_maps.append(img * data['seg_mask'][idx,0])
        for i in range(lm_maps.size(0)):
            img_map = img * lm_maps[i]
            img_maps.append(img_map)

        img_maps = torch.stack(img_maps)
        img_maps = torchvision.utils.make_grid(img_maps, nrow=10, normalize = True).cpu().numpy()
        img_maps = img_maps.transpose([1,2,0])
        img_maps = img_maps[:,:,[2,1,0]] # from RGB to BGR
        image.imshow(img_maps)

if __name__ == '__main__':
    # test_AttributeDataset()
    # test_EXPAttributeDataset()
    test_GANDataset()