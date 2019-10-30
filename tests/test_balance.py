import time

import pytest
import torch
from torch import nn

from torchgpipe.balance import balance_by_size, balance_by_time, blockpartition

skip_if_no_cuda = pytest.mark.skipif(not torch.cuda.is_available(), reason='cuda required')

devices = ['cpu']
if torch.cuda.is_available():
    devices.append('cuda')


def test_blockpartition():
    assert blockpartition.solve([1, 2, 3, 4, 5, 6], partitions=2) == [[1, 2, 3, 4], [5, 6]]


def test_blockpartition_zeros():
    assert blockpartition.solve([0, 0], partitions=2) == [[0], [0]]


def test_blockpartition_non_positive_partitions():
    with pytest.raises(ValueError):
        blockpartition.solve([42], partitions=0)
    with pytest.raises(ValueError):
        blockpartition.solve([42], partitions=-1)


def test_blockpartition_short_sequence():
    with pytest.raises(ValueError):
        blockpartition.solve([], partitions=1)
    with pytest.raises(ValueError):
        blockpartition.solve([42], partitions=2)


def test_balance_by_time():
    class Delay(nn.Module):
        def __init__(self, seconds):
            super().__init__()
            self.seconds = seconds

        def forward(self, x):
            time.sleep(self.seconds)
            return x

    model = nn.Sequential(*[Delay(i/100) for i in [1, 2, 3, 4, 5, 6]])
    sample = torch.rand(1)
    balance = balance_by_time(2, model, sample)
    assert balance == [4, 2]


@skip_if_no_cuda
def test_balance_by_size_latent():
    class Expand(nn.Module):
        def __init__(self, times):
            super().__init__()
            self.times = times

        def forward(self, x):
            for i in range(self.times):
                x = x + torch.rand_like(x, requires_grad=True)
            return x

    sample = torch.rand(10, 100, 100, device='cuda')

    model = nn.Sequential(*[Expand(i) for i in [1, 2, 3, 4, 5, 6]]).to('cuda')
    balance = balance_by_size(2, model, sample)
    assert balance == [4, 2]

    model = nn.Sequential(*[Expand(i) for i in [6, 5, 4, 3, 2, 1]]).to('cuda')
    balance = balance_by_size(2, model, sample)
    assert balance == [2, 4]


@skip_if_no_cuda
def test_balance_by_size_param():
    model = nn.Sequential(*[nn.Linear(i+1, i+2) for i in range(6)]).to('cuda')
    sample = torch.rand(7, 1, device='cuda')
    balance = balance_by_size(2, model, sample, param_scale=100)
    assert balance == [4, 2]

    model = nn.Sequential(*[nn.Linear(i+2, i+1) for i in reversed(range(6))]).to('cuda')
    sample = torch.rand(1, 7, device='cuda')
    balance = balance_by_size(2, model, sample, param_scale=100)
    assert balance == [2, 4]


@skip_if_no_cuda
def test_balance_by_size_param_scale():
    class Tradeoff(nn.Module):
        def __init__(self, param_size, latent_size):
            super().__init__()
            self.fc = nn.Linear(param_size, param_size)
            self.latent_size = latent_size

        def forward(self, x):
            for i in range(self.latent_size):
                x = x + torch.rand_like(x, requires_grad=True)
            return x

    model = nn.Sequential(
        Tradeoff(param_size=1, latent_size=6),
        Tradeoff(param_size=2, latent_size=5),
        Tradeoff(param_size=3, latent_size=4),
        Tradeoff(param_size=4, latent_size=3),
        Tradeoff(param_size=5, latent_size=2),
        Tradeoff(param_size=6, latent_size=1),
    ).to('cuda')

    sample = torch.rand(1, requires_grad=True, device='cuda')

    balance = balance_by_size(2, model, sample, param_scale=0)
    assert balance == [2, 4]

    balance = balance_by_size(2, model, sample, param_scale=100)
    assert balance == [4, 2]


@pytest.mark.parametrize('device', devices)
def test_sandbox(device):
    model = nn.Sequential(nn.BatchNorm2d(3)).to(device)

    before = {k: v.clone() for k, v in model.state_dict().items()}

    sample = torch.rand(1, 3, 10, 10, device=device)
    balance_by_time(1, model, sample)

    after = model.state_dict()

    assert before.keys() == after.keys()
    for key, value in before.items():
        assert torch.allclose(after[key], value), key


def test_not_training():
    class AssertTraining(nn.Module):
        def forward(self, x):
            assert self.training
            return x
    model = nn.Sequential(AssertTraining())

    model.eval()
    assert not model.training

    sample = torch.rand(1)
    balance_by_time(1, model, sample)

    assert not model.training


def test_deprecated_torchgpipe_balancing():
    with pytest.raises(ImportError, match='torchgpipe.balance'):
        __import__('torchgpipe_balancing')


def test_balance_by_time_tuple():
    class Twin(nn.Module):
        def forward(self, x):
            return x, x.detach()

    class Add(nn.Module):
        def forward(self, a_b):
            a, b = a_b
            return a + b

    model = nn.Sequential(Twin(), Add())
    sample = torch.rand(1, requires_grad=True)
    balance_by_time(1, model, sample)


@skip_if_no_cuda
def test_balance_by_size_tuple():
    class Twin(nn.Module):
        def forward(self, x):
            return x, x.detach()

    class Add(nn.Module):
        def forward(self, a_b):
            a, b = a_b
            return a + b

    model = nn.Sequential(Twin(), Add()).to('cuda')
    sample = torch.rand(1, requires_grad=True, device='cuda')
    balance_by_size(1, model, sample)