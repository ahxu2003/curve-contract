import pytest
import requests

from brownie import Contract, ERC20Mock, ERC20MockNoReturn
from brownie.convert import to_address

from conftest import WRAPPED_COIN_METHODS

_holders = {}


# public fixtures - these can be used when testing

@pytest.fixture(scope="module")
def wrapped_coins(project, alice, pool_data, _underlying_coins, is_forked):
    return _wrapped(project, alice, pool_data, _underlying_coins, is_forked)


@pytest.fixture(scope="module")
def underlying_coins(_underlying_coins, _base_coins):
    if _base_coins:
        return _underlying_coins[:1] + _base_coins
    else:
        return _underlying_coins


@pytest.fixture(scope="module")
def pool_token(project, alice, pool_data):
    return _pool_token(project, alice, pool_data)


@pytest.fixture(scope="module")
def base_pool_token(project, charlie, base_pool_data, is_forked):
    if base_pool_data is None:
        return
    if is_forked:
        return _MintableTestToken(base_pool_data["lp_token_address"], base_pool_data)

    # we do some voodoo here to make the base LP tokens work like test ERC20's
    # charlie is the initial liquidity provider, he starts with the full balance
    def _mint_for_testing(target, amount, tx=None):
        token.transfer(target, amount, {'from': charlie})

    token = _pool_token(project, charlie, base_pool_data)
    token._mint_for_testing = _mint_for_testing
    return token


# private API below

class _MintableTestToken(Contract):

    def __init__(self, address, pool_data):
        super().__init__(address)

        # standardize mint / rate methods
        if 'wrapped_contract' in pool_data:
            fn_names = WRAPPED_COIN_METHODS[pool_data['wrapped_contract']]
            for target, attr in fn_names.items():
                if hasattr(self, attr):
                    setattr(self, target, getattr(self, attr))

        # get top token holder addresses
        address = self.address
        if address not in _holders:
            holders = requests.get(
                f"https://api.ethplorer.io/getTopTokenHolders/{address}",
                params={'apiKey': "freekey", 'limit': 50},
            ).json()
            _holders[address] = [to_address(i['address']) for i in holders['holders']]

    def _mint_for_testing(self, target, amount, tx=None):
        if self.address == "0x674C6Ad92Fd080e4004b2312b45f796a192D27a0":
            # special case for minting USDN
            self.deposit(target, amount, {'from': "0x90f85042533F11b362769ea9beE20334584Dcd7D"})
            return
        if self.address == "0x0E2EC54fC0B509F445631Bf4b91AB8168230C752":
            self.mint(target, amount, {'from': "0x62F31E08e279f3091d9755a09914DF97554eAe0b"})
            return

        for address in _holders[self.address].copy():
            if address == self.address:
                # don't claim from the treasury - that could cause wierdness
                continue

            balance = self.balanceOf(address)
            if amount > balance:
                self.transfer(target, balance, {'from': address})
                amount -= balance
            else:
                self.transfer(target, amount, {'from': address})
                return

        raise ValueError(f"Insufficient tokens available to mint {self.name()}")


def _wrapped(project, alice, pool_data, underlying_coins, is_forked):
    coins = []

    if not pool_data.get("wrapped_contract"):
        return underlying_coins

    if is_forked:
        for i, coin_data in enumerate(pool_data['coins']):
            if not coin_data['wrapped']:
                coins.append(underlying_coins[i])
            else:
                coins.append(_MintableTestToken(coin_data['wrapped_address'], pool_data))
        return coins

    fn_names = WRAPPED_COIN_METHODS[pool_data['wrapped_contract']]
    deployer = getattr(project, pool_data['wrapped_contract'])
    for i, coin_data in enumerate(pool_data['coins']):
        underlying = underlying_coins[i]
        if not coin_data['wrapped']:
            coins.append(underlying)
        else:
            decimals = coin_data['wrapped_decimals']
            name = coin_data.get("name", f"Coin {i}")
            symbol = coin_data.get("name", f"C{i}")
            contract = deployer.deploy(name, symbol, decimals, underlying, {'from': alice})
            for target, attr in fn_names.items():
                setattr(contract, target, getattr(contract, attr))
            if coin_data.get("withdrawal_fee"):
                contract._set_withdrawal_fee(coin_data["withdrawal_fee"], {'from': alice})
            coins.append(contract)
    return coins


def _underlying(alice, pool_data, is_forked, base_pool_token):
    coins = []

    if is_forked:
        for data in pool_data['coins']:
            coins.append(_MintableTestToken(data['underlying_address'], pool_data))
    else:
        for i, coin_data in enumerate(pool_data['coins']):
            if coin_data.get("base_pool_token"):
                coins.append(base_pool_token)
                continue
            decimals = coin_data['decimals']
            deployer = ERC20MockNoReturn if coin_data['tethered'] else ERC20Mock
            contract = deployer.deploy(f"Underlying Coin {i}", f"UC{i}", decimals, {'from': alice})
            coins.append(contract)

    return coins


def _pool_token(project, alice, pool_data):
    name = pool_data['name']
    deployer = getattr(project, pool_data['lp_contract'])
    return deployer.deploy(f"Curve {name} LP Token", f"{name}CRV", 18, 0, {'from': alice})


# private fixtures used for setup in other fixtures - do not use in tests!

@pytest.fixture(scope="module")
def _underlying_coins(alice, pool_data, is_forked, base_pool_token, _add_base_pool_liquidity):
    return _underlying(alice, pool_data, is_forked, base_pool_token)


@pytest.fixture(scope="module")
def _base_coins(alice, base_pool_data, is_forked):
    if base_pool_data is None:
        return []
    return _underlying(alice, base_pool_data, is_forked, None)
